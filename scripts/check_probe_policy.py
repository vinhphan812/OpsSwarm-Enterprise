#!/usr/bin/env python3
"""Positive probe-policy check for a rendered Kubernetes manifest.

This is the executable form of the container-delivery probe contract.  It
asserts the *correct* configuration rather than the absence of a probe:

* every application container declares exactly one ``readinessProbe``;
* the readiness probe targets ``/ready`` (the fail-closed readiness gate);
* the readiness probe never targets ``/health`` (a liveness signal);
* the liveness probe targets ``/health`` and stays independent of the
  HA / Postgres gate.

The script exits ``0`` when the manifest satisfies the policy and ``1``
with a clear diagnostic when it does not.  It is used by the
``container-delivery`` workflow against the rendered dev overlay and by the
unit tests against fixtures that violate each rule in turn.

Usage::

    python scripts/check_probe_policy.py path/to/rendered.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

READINESS_PATH = "/ready"
LIVENESS_PATH = "/health"

# Container names that are not the application container (for example
# injected sidecars) are not required to carry the OpsSwarm probe contract.
_IGNORED_CONTAINER_NAMES = frozenset({"openclaw-check"})


class ProbePolicyError(Exception):
    """Raised when a rendered manifest violates the probe policy."""


def _application_containers(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    spec = deployment.get("spec") or {}
    template = spec.get("template") or {}
    pod_spec = template.get("spec") or {}
    containers = pod_spec.get("containers") or []
    return [
        container
        for container in containers
        if container.get("name") not in _IGNORED_CONTAINER_NAMES
    ]


def _probe_path(container: dict[str, Any], probe_name: str) -> str | None:
    probe = container.get(probe_name)
    if not isinstance(probe, dict):
        return None
    http_get = probe.get("httpGet")
    if not isinstance(http_get, dict):
        return None
    path = http_get.get("path")
    return path if isinstance(path, str) else None


def check_manifest(documents: list[Any]) -> None:
    """Validate the probe policy of every Deployment in ``documents``.

    Raises:
        ProbePolicyError: when a Deployment violates the probe policy.
    """
    deployments = [
        doc
        for doc in documents
        if isinstance(doc, dict) and doc.get("kind") == "Deployment"
    ]
    if not deployments:
        raise ProbePolicyError("the manifest contains no Deployment")

    for deployment in deployments:
        name = (deployment.get("metadata") or {}).get("name", "<unnamed>")
        for container in _application_containers(deployment):
            container_name = container.get("name", "<unnamed>")

            readiness = container.get("readinessProbe")
            if readiness is None:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    "a readinessProbe is required"
                )
            readiness_path = _probe_path(container, "readinessProbe")
            if readiness_path is None:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    "the readinessProbe must use an httpGet probe"
                )
            if readiness_path == LIVENESS_PATH:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    "the readinessProbe must not use /health; /health is a "
                    "liveness signal, not a readiness gate"
                )
            if readiness_path != READINESS_PATH:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    f"the readinessProbe must target {READINESS_PATH}, "
                    f"got '{readiness_path}'"
                )

            liveness_path = _probe_path(container, "livenessProbe")
            if liveness_path is None:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    "a livenessProbe on /health is required"
                )
            if liveness_path != LIVENESS_PATH:
                raise ProbePolicyError(
                    f"Deployment '{name}' container '{container_name}': "
                    f"the livenessProbe must target {LIVENESS_PATH}, "
                    f"got '{liveness_path}'"
                )


def check_file(path: Path) -> None:
    """Validate the probe policy of the YAML manifest at ``path``."""
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    check_manifest(documents)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <rendered-manifest.yaml>", file=sys.stderr)
        return 2
    manifest = Path(argv[1])
    if not manifest.is_file():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 1
    try:
        check_file(manifest)
    except ProbePolicyError as exc:
        print(f"PROBE POLICY VIOLATION: {exc}", file=sys.stderr)
        return 1
    print(f"Probe policy satisfied: {manifest}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main(sys.argv))
