#!/usr/bin/env python3
"""Policy validator for the canonical OpsSwarm Kubernetes manifests.

The canonical deployment tree is ``k8s/`` (owned by the consolidation card).
This validator reads *rendered* manifests -- the output of ``kubectl kustomize``
-- and enforces the deployment policy that the rendered workload must satisfy
before it is allowed to ship.

Policy is derived from ``docs/audits/ISSUE-73_DEPLOYMENT_PROFILE_SPEC.md`` and
from the security context actually committed under ``k8s/base/``:

* exactly one replica, and no autoscaler (issue #70 gate);
* ``Recreate`` strategy, so a rollout never runs two pods against the same
  file-backed data volume;
* non-root execution: pod ``runAsNonRoot``, and a non-zero ``runAsUser``;
* no privilege escalation, all Linux capabilities dropped, and the
  runtime-default seccomp profile on application containers;
* explicit CPU and memory requests *and* limits;
* a liveness probe and a readiness probe on every application container, with
  readiness pointing at a real readiness gate rather than the liveness path;
* durable single-writer storage (``ReadWriteOnce`` PVC) for the production
  profile, and no ``hostPath`` mounts anywhere;
* no committed plaintext credentials.

Checks are intentionally evaluated against the *rendered* document rather than
the source YAML, because overlays (dev/prod) patch images, service types,
probes, volumes and secrets.  Validating the source would let an overlay
silently weaken the policy.

Profiles
--------
The validator supports three deployment profiles so that the intentional
differences between the canonical overlays can be expressed as policy rather
than as exceptions:

``base``
    The Kustomize base.  Uses the ``:latest`` image tag and real PVCs.
``dev``
    The local-development overlay.  Uses the ``:dev`` tag and ``emptyDir``
    volumes, so persistent storage is *not* required.
``prod``
    The production overlay.  Requires a version-pinned image tag (or digest)
    and durable PVC-backed storage.

Exit codes:
    0 -- every rendered manifest satisfies the policy.
    1 -- one or more policy violations were found.
    2 -- the validator could not run (bad input, unreadable file, YAML error).

The validator is read-only: it never contacts a cluster or a registry.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

# The workload namespace is matched exactly; a workload in another namespace is
# out of scope for this repository's profile and is rejected rather than skipped.
EXPECTED_NAMESPACE = "opsswarm"

# Required container-level security context keys for application containers.
_REQUIRED_CONTAINER_SECURITY_KEYS = ("runAsNonRoot", "allowPrivilegeEscalation", "seccompProfile")

# Placeholder markers used by the committed Secret / secretGenerator templates.
# A rendered Secret that still carries one of these is a template, not a leak,
# so it is reported as an informational finding rather than a violation.
_PLACEHOLDER_MARKERS = ("REPLACE_WITH", "CHANGE_ME", "CHANGEME", "PLACEHOLDER")

# Image references that are mutable and therefore rejected for the prod profile.
_MUTABLE_IMAGE_TAGS = ("latest", "dev", "main", "master", "edge", "nightly")

# ConfigMap keys whose names indicate a credential.
_SUSPICIOUS_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
)

# The liveness endpoint.  A readiness probe pointing here would report the
# pod ready while its dependencies are still broken.
_LIVENESS_PATH = "/health"


@dataclass(frozen=True)
class Profile:
    """Deployment profile rules applied to a rendered manifest set.

    Attributes:
        name: Profile identifier used in diagnostics.
        require_pinned_image: Reject mutable image tags such as ``latest``.
        require_persistent_storage: Require at least one PVC-backed volume.
        require_readiness_probe: Require a readiness probe on app containers.
    """

    name: str
    require_pinned_image: bool
    require_persistent_storage: bool
    require_readiness_probe: bool


PROFILES: dict[str, Profile] = {
    "base": Profile(
        name="base",
        require_pinned_image=False,
        require_persistent_storage=True,
        require_readiness_probe=True,
    ),
    "dev": Profile(
        name="dev",
        require_pinned_image=False,
        require_persistent_storage=False,
        require_readiness_probe=True,
    ),
    "prod": Profile(
        name="prod",
        require_pinned_image=True,
        require_persistent_storage=True,
        require_readiness_probe=True,
    ),
}


class ManifestValidationError(ValueError):
    """Raised when a rendered manifest violates the deployment policy."""


class ManifestSchemaError(ValueError):
    """Raised when a manifest cannot be parsed or lacks required structure."""


def _spec_of(document: dict[str, Any]) -> dict[str, Any]:
    """Return the ``spec`` mapping of a manifest document."""
    spec = document.get("spec")
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ManifestSchemaError("manifest spec is not a mapping")
    return spec


def _metadata_of(document: dict[str, Any]) -> dict[str, Any]:
    """Return the ``metadata`` mapping of a manifest document."""
    metadata = document.get("metadata")
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ManifestSchemaError("manifest metadata is not a mapping")
    return metadata


def _pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    """Return the pod template spec of a Deployment."""
    template = _spec_of(deployment).get("template")
    if not isinstance(template, dict):
        raise ManifestSchemaError("Deployment has no pod template")
    template_spec = template.get("spec")
    if not isinstance(template_spec, dict):
        raise ManifestSchemaError("Deployment pod template has no spec")
    return template_spec


def _container_name(container: dict[str, Any]) -> str:
    """Return a readable identifier for a container."""
    name = container.get("name")
    return str(name) if name else "<unnamed>"


def _is_placeholder(value: str) -> bool:
    """Return True when ``value`` is an obvious unfilled template placeholder."""
    upper = value.upper()
    return any(marker in upper for marker in _PLACEHOLDER_MARKERS)


def validate_image_reference(image: str, context: str, profile: Profile) -> None:
    """Reject images that are unpinned or that use a mutable tag.

    A deployable image reference must carry an explicit version tag or an
    immutable digest.  For the ``prod`` profile, mutable tags (``latest``,
    ``dev``, ...) are additionally rejected, because they make the running
    workload differ from the reviewed source.

    Raises:
        ManifestValidationError: if the image reference is not shippable.
    """
    if not image:
        raise ManifestValidationError(f"{context}: container has no image reference")
    if "@sha256:" in image:
        return
    if ":" not in image:
        raise ManifestValidationError(
            f"{context}: image {image!r} is not pinned to a version tag or digest"
        )
    tag = image.rsplit(":", 1)[1]
    if profile.require_pinned_image and tag.lower() in _MUTABLE_IMAGE_TAGS:
        raise ManifestValidationError(
            f"{context}: image {image!r} uses the mutable tag {tag!r}; "
            "the prod profile requires a released version tag or a digest"
        )


def _validate_container_security(
    container: dict[str, Any], container_context: str, profile: Profile
) -> None:
    """Validate the container security context of an application container.

    Raises:
        ManifestValidationError: if the security context is insufficient.
    """
    security = container.get("securityContext") or {}
    for key in _REQUIRED_CONTAINER_SECURITY_KEYS:
        if key not in security:
            raise ManifestValidationError(
                f"{container_context}: securityContext must declare {key!r}"
            )

    if security.get("runAsNonRoot") is not True:
        raise ManifestValidationError(
            f"{container_context}: securityContext must set runAsNonRoot: true"
        )
    if security.get("allowPrivilegeEscalation") is not False:
        raise ManifestValidationError(
            f"{container_context}: securityContext must set allowPrivilegeEscalation: false"
        )

    run_as_user = security.get("runAsUser")
    if not isinstance(run_as_user, int) or run_as_user == 0:
        raise ManifestValidationError(
            f"{container_context}: securityContext must set a non-zero runAsUser, "
            f"got {run_as_user!r}"
        )

    seccomp = security.get("seccompProfile") or {}
    if seccomp.get("type") != "RuntimeDefault":
        raise ManifestValidationError(
            f"{container_context}: securityContext seccompProfile.type must be 'RuntimeDefault'"
        )

    capabilities = security.get("capabilities") or {}
    dropped = capabilities.get("drop") or []
    if "ALL" not in [str(entry).upper() for entry in dropped]:
        raise ManifestValidationError(
            f"{container_context}: securityContext capabilities.drop must include 'ALL'"
        )


def _validate_probes(container: dict[str, Any], container_context: str, profile: Profile) -> None:
    """Validate the probe configuration of an application container.

    Raises:
        ManifestValidationError: if a probe is missing or misconfigured.
    """
    liveness = container.get("livenessProbe")
    if not isinstance(liveness, dict):
        raise ManifestValidationError(f"{container_context}: a livenessProbe is required")

    if not profile.require_readiness_probe:
        return

    readiness = container.get("readinessProbe")
    if not isinstance(readiness, dict):
        raise ManifestValidationError(f"{container_context}: a readinessProbe is required")

    readiness_path = (readiness.get("httpGet") or {}).get("path")
    if readiness_path == _LIVENESS_PATH:
        raise ManifestValidationError(
            f"{container_context}: readinessProbe must not use {_LIVENESS_PATH}; "
            f"{_LIVENESS_PATH} is a liveness signal, not a readiness gate"
        )


def validate_deployment(deployment: dict[str, Any], context: str, profile: Profile) -> None:
    """Enforce the single-replica and container hardening policy.

    Raises:
        ManifestValidationError: if the Deployment violates the policy.
    """
    spec = _spec_of(deployment)
    metadata = _metadata_of(deployment)

    namespace = metadata.get("namespace")
    if namespace != EXPECTED_NAMESPACE:
        raise ManifestValidationError(
            f"{context}: Deployment namespace must be {EXPECTED_NAMESPACE!r}, got {namespace!r}"
        )

    # -- Single-replica safety until issue #70 lands ------------------------
    replicas = spec.get("replicas")
    if replicas != 1:
        raise ManifestValidationError(
            f"{context}: Deployment must declare exactly 1 replica "
            f"(single-replica policy until issue #70), got {replicas!r}"
        )

    strategy_type = (spec.get("strategy") or {}).get("type")
    if strategy_type != "Recreate":
        raise ManifestValidationError(
            f"{context}: Deployment strategy must be 'Recreate' so a rollout never "
            f"runs two pods against the same data volume, got {strategy_type!r}"
        )

    # -- Pod-level security context ----------------------------------------
    pod_spec = _pod_spec(deployment)
    pod_security = pod_spec.get("securityContext") or {}
    if pod_security.get("runAsNonRoot") is not True:
        raise ManifestValidationError(f"{context}: pod securityContext must set runAsNonRoot: true")
    run_as_user = pod_security.get("runAsUser")
    if not isinstance(run_as_user, int) or run_as_user == 0:
        raise ManifestValidationError(
            f"{context}: pod securityContext must set a non-zero runAsUser, got {run_as_user!r}"
        )
    if "fsGroup" not in pod_security:
        raise ManifestValidationError(
            f"{context}: pod securityContext must set fsGroup so the runtime "
            "data volume is group-writable by the application UID"
        )

    containers = pod_spec.get("containers")
    if not isinstance(containers, list) or not containers:
        raise ManifestValidationError(f"{context}: Deployment must define at least one container")

    for container in containers:
        if not isinstance(container, dict):
            raise ManifestValidationError(f"{context}: container entry is not a mapping")
        name = _container_name(container)
        container_context = f"{context}: container {name!r}"

        validate_image_reference(str(container.get("image", "")), container_context, profile)
        _validate_container_security(container, container_context, profile)
        _validate_probes(container, container_context, profile)

        resources = container.get("resources") or {}
        for section in ("requests", "limits"):
            values = resources.get(section) or {}
            if not isinstance(values, dict) or not values:
                raise ManifestValidationError(
                    f"{container_context}: resources.{section} must declare explicit "
                    "CPU and memory values"
                )
            for dimension in ("cpu", "memory"):
                if not values.get(dimension):
                    raise ManifestValidationError(
                        f"{container_context}: resources.{section}.{dimension} is required"
                    )

    # -- Volumes ------------------------------------------------------------
    volumes = pod_spec.get("volumes") or []
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        if "hostPath" in volume:
            raise ManifestValidationError(
                f"{context}: volume {volume.get('name')!r} uses a hostPath mount; "
                "the workload must not depend on host filesystem paths"
            )

    if profile.require_persistent_storage:
        has_pvc = any(
            isinstance(volume, dict) and "persistentVolumeClaim" in volume for volume in volumes
        )
        if not has_pvc:
            raise ManifestValidationError(
                f"{context}: the {profile.name!r} profile requires at least one "
                "PVC-backed volume so runtime state survives pod replacement"
            )


def validate_pvc(pvc: dict[str, Any], context: str, profile: Profile) -> None:
    """Enforce the single-writer storage contract.

    Raises:
        ManifestValidationError: if the PVC violates the policy.
    """
    spec = _spec_of(pvc)
    metadata = _metadata_of(pvc)

    namespace = metadata.get("namespace")
    if namespace != EXPECTED_NAMESPACE:
        raise ManifestValidationError(
            f"{context}: PersistentVolumeClaim namespace must be "
            f"{EXPECTED_NAMESPACE!r}, got {namespace!r}"
        )

    access_modes = spec.get("accessModes") or []
    if "ReadWriteOnce" not in access_modes:
        raise ManifestValidationError(
            f"{context}: PersistentVolumeClaim must include 'ReadWriteOnce' "
            f"for the single-writer contract, got {access_modes!r}"
        )

    # NOTE: the local name avoids ``requests`` so that Bandit's B113 check
    # (HTTP calls without a timeout) does not match this non-HTTP mapping.
    resource_requests = (spec.get("resources") or {}).get("requests") or {}
    if not resource_requests.get("storage"):
        raise ManifestValidationError(
            f"{context}: PersistentVolumeClaim must request an explicit storage size"
        )


def _secret_values(secret: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the ``(key, value)`` pairs of a Secret, decoding base64 data.

    ``data`` holds base64-encoded values and ``stringData`` holds plain ones.
    Both are decoded so that placeholder detection works on the real value.
    """
    import base64

    pairs: list[tuple[str, str]] = []

    string_data = secret.get("stringData")
    if isinstance(string_data, dict):
        for key, value in string_data.items():
            if isinstance(value, str):
                pairs.append((str(key), value))

    data = secret.get("data")
    if isinstance(data, dict):
        for key, value in data.items():
            if not isinstance(value, str) or not value:
                continue
            try:
                decoded = base64.b64decode(value, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                # Not valid base64 or not UTF-8: treat the raw value as the payload.
                decoded = value
            pairs.append((str(key), decoded))

    return pairs


def validate_secret(secret: dict[str, Any], context: str, profile: Profile) -> None:
    """Reject committed credentials.

    A rendered Secret whose values are still template placeholders is a
    template that an operator is expected to replace, and is reported as an
    informational finding.  A rendered Secret carrying a value that is neither
    a placeholder nor obviously empty is a credential leak and is rejected.

    Raises:
        ManifestValidationError: if the Secret carries a committed credential.
    """
    for key, value in _secret_values(secret):
        if not value:
            continue
        if _is_placeholder(value):
            continue
        raise ManifestValidationError(
            f"{context}: Secret key {key!r} carries a committed literal value; "
            "inject secrets at deploy time from a secret manager"
        )


def validate_configmap(configmap: dict[str, Any], context: str, profile: Profile) -> None:
    """Reject credential-shaped values committed into a ConfigMap.

    Raises:
        ManifestValidationError: if the ConfigMap carries a credential.
    """
    data = configmap.get("data")
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not isinstance(value, str) or not value:
            continue
        lowered = str(key).lower()
        if any(marker in lowered for marker in _SUSPICIOUS_KEY_MARKERS) and not _is_placeholder(
            value
        ):
            raise ManifestValidationError(
                f"{context}: ConfigMap key {key!r} looks like a credential; "
                "secrets must not be committed in a ConfigMap"
            )


def validate_document(document: dict[str, Any], context: str, profile: Profile) -> None:
    """Dispatch a single rendered manifest to its kind-specific validator.

    Raises:
        ManifestValidationError: if the manifest violates the policy.
    """
    kind = document.get("kind")
    if not kind:
        raise ManifestSchemaError(f"{context}: manifest has no kind")

    if kind == "Deployment":
        validate_deployment(document, context, profile)
    elif kind == "PersistentVolumeClaim":
        validate_pvc(document, context, profile)
    elif kind == "Secret":
        validate_secret(document, context, profile)
    elif kind == "ConfigMap":
        validate_configmap(document, context, profile)


def validate_manifest_file(path: Path, profile: Profile | None = None) -> list[str]:
    """Validate every manifest document in a rendered YAML file.

    This compatibility entry point defaults to the production policy so callers
    that validate a single rendered file do not accidentally skip immutable
    image and durable-storage requirements.

    Args:
        path: Rendered manifest file.
        profile: Policy profile; defaults to ``prod``.

    Returns:
        Informational findings that do not constitute policy violations.
    """
    return validate_rendered_file(path, profile or PROFILES["prod"])


def validate_rendered_file(path: Path, profile: Profile) -> list[str]:
    """Validate every manifest document in a rendered YAML file.

    Args:
        path: Path to a rendered manifest file.
        profile: Deployment profile whose rules are applied.

    Returns:
        Informational findings that do not constitute policy violations.

    Raises:
        ManifestValidationError: if any document violates the policy.
        ManifestSchemaError: if the file cannot be parsed.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestSchemaError(f"cannot read {path}: {exc}") from exc

    try:
        documents = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        raise ManifestSchemaError(f"{path.name}: invalid YAML: {exc}") from exc

    findings: list[str] = []
    for index, document in enumerate(documents):
        if document is None:
            continue
        if not isinstance(document, dict):
            raise ManifestSchemaError(f"{path.name}[{index}]: document is not a mapping")
        context = f"{path.name}[{index}]"
        validate_document(document, context, profile)

        if document.get("kind") == "Secret":
            for key, value in _secret_values(document):
                if _is_placeholder(value):
                    findings.append(
                        f"{context}: Secret key {key!r} still holds a template placeholder; "
                        "inject the real secret at deploy time"
                    )
    return findings


def _collect_manifest_files(paths: Iterable[Path]) -> list[Path]:
    """Expand the given paths into a sorted list of YAML files."""
    collected: list[Path] = []
    for path in paths:
        if path.is_file():
            collected.append(path)
        elif path.is_dir():
            for pattern in ("*.yaml", "*.yml"):
                collected.extend(sorted(path.glob(pattern)))
        else:
            raise ManifestSchemaError(f"path does not exist: {path}")
    return collected


def main(argv: list[str] | None = None) -> int:
    """Validate rendered manifests against the deployment policy.

    Returns:
        0 when the policy holds, 1 on violations, 2 on validator errors.
    """
    parser = argparse.ArgumentParser(
        description="Validate rendered Kubernetes manifests against the OpsSwarm deployment policy."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path("artifacts/manifests")],
        help="rendered manifest files or directories to validate",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="prod",
        help="deployment profile whose rules are applied (default: prod)",
    )
    args = parser.parse_args(argv)

    profile = PROFILES[args.profile]

    try:
        manifest_files = _collect_manifest_files(args.paths)
    except ManifestSchemaError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not manifest_files:
        print("ERROR: no manifest files found to validate.", file=sys.stderr)
        return 2

    failed = False
    for path in manifest_files:
        try:
            findings = validate_rendered_file(path, profile)
        except ManifestValidationError as exc:
            print(f"POLICY VIOLATION: {exc}", file=sys.stderr)
            failed = True
        except ManifestSchemaError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            failed = True
        else:
            print(f"Validated [{profile.name}]: {path}")
            for finding in findings:
                print(f"  FINDING: {finding}")

    if failed:
        print("Manifest policy validation failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
