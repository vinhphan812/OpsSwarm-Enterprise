"""Workflow-logic tests for the container-delivery evidence pipeline.

These tests exercise the *logic* of the container-delivery workflow and the
Kubernetes manifests it renders, without needing a registry, a cluster or a
Docker daemon.  They exist so that the failure modes that sank the earlier
candidate PRs cannot come back unnoticed:

1. **Unresolvable action pins.**  Every third-party action must be pinned to
   a full 40-character commit SHA.  A truncated or non-SHA pin cannot be
   resolved by the Actions runner and fails the job with
   ``Unable to resolve action``.
2. **Image-repository drift.**  The workflow must push to the *same* image
   repository the Kubernetes manifests reference, otherwise the digest pin
   written into the overlay is silently dropped by kustomize.
3. **Digest assertions.**  The published digest must be asserted against
   ``^sha256:[a-f0-9]{64}$`` before it is used as evidence.
4. **Manifest policy.**  The rendered production overlay must not enable
   broad public ingress and must gate readiness on ``/ready``.

The rendering assertions are skipped when neither ``kubectl`` nor
``kustomize`` is available, so the suite stays runnable everywhere.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CONTAINER_DELIVERY_WORKFLOW = WORKFLOWS_DIR / "container-delivery.yml"
RELEASE_WORKFLOW = WORKFLOWS_DIR / "release.yml"

K8S_DIR = REPO_ROOT / "k8s"
K8S_BASE = K8S_DIR / "base"
DEV_OVERLAY = K8S_DIR / "overlays" / "dev"
PROD_OVERLAY = K8S_DIR / "overlays" / "prod"

CANONICAL_IMAGE_REPO = "ghcr.io/vinhphan812/opsswarm-enterprise"
DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")

# Matches "uses: owner/repo@<ref>" in a workflow file.
USES_PATTERN = re.compile(r"^\s*uses:\s*(?P<repo>[\w.-]+/[\w.-]+)@(?P<ref>\S+)", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _render(overlay: Path) -> str | None:
    """Render a kustomize overlay, or return None when no renderer exists."""
    if shutil.which("kubectl"):
        result = subprocess.run(
            ["kubectl", "kustomize", str(overlay)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    if shutil.which("kustomize"):
        result = subprocess.run(
            ["kustomize", "build", str(overlay)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    return None


# ---------------------------------------------------------------------------
# Action pin hygiene
# ---------------------------------------------------------------------------


class TestActionPinsAreResolvableShas:
    """Every third-party action must be pinned to a full commit SHA."""

    @pytest.mark.parametrize(
        "workflow",
        [CONTAINER_DELIVERY_WORKFLOW, RELEASE_WORKFLOW],
        ids=["container-delivery", "release"],
    )
    def test_all_uses_are_pinned_to_a_full_sha(self, workflow):
        """A pin must be exactly 40 hex characters — nothing shorter."""
        if not workflow.is_file():
            pytest.skip(f"{workflow.name} not present")

        content = _read(workflow)
        offenders = []
        for match in USES_PATTERN.finditer(content):
            ref = match.group("ref")
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                offenders.append(f"{match.group('repo')}@{ref}")
        assert not offenders, (
            "Every action must be pinned to a full 40-character commit SHA; "
            f"unpinned or truncated pins found: {offenders}"
        )

    def test_container_delivery_uses_the_resolvable_login_action_pin(self):
        """The login-action pin must be the one that actually resolves."""
        if not CONTAINER_DELIVERY_WORKFLOW.is_file():
            pytest.skip("container-delivery.yml not present")

        content = _read(CONTAINER_DELIVERY_WORKFLOW)
        pins = set(USES_PATTERN.findall(content))
        login_pins = {ref for repo, ref in pins if repo == "docker/login-action"}
        assert login_pins == {"9780b0c442fbb1117ed29e0efdff1e18412f7567"}, (
            "container-delivery.yml must pin docker/login-action to the "
            "resolvable v3 commit SHA 9780b0c442fbb1117ed29e0efdff1e18412f7567; "
            f"found {login_pins}"
        )

    def test_container_delivery_uses_the_resolvable_buildx_pin(self):
        """The setup-buildx-action pin must be the one that actually resolves."""
        if not CONTAINER_DELIVERY_WORKFLOW.is_file():
            pytest.skip("container-delivery.yml not present")

        content = _read(CONTAINER_DELIVERY_WORKFLOW)
        pins = set(USES_PATTERN.findall(content))
        buildx_pins = {ref for repo, ref in pins if repo == "docker/setup-buildx-action"}
        assert buildx_pins == {"f7ce87c1d6bead3e36075b2ce75da1f6cc28aaca"}, (
            "container-delivery.yml must pin docker/setup-buildx-action to the "
            "resolvable v3 commit SHA f7ce87c1d6bead3e36075b2ce75da1f6cc28aaca; "
            f"found {buildx_pins}"
        )


# ---------------------------------------------------------------------------
# Image repository alignment
# ---------------------------------------------------------------------------


class TestImageRepositoryAlignment:
    """The workflow and the manifests must agree on the image repository."""

    def test_workflow_publishes_to_the_canonical_repository(self):
        """IMAGE_REPO must be the repository the manifests reference."""
        if not CONTAINER_DELIVERY_WORKFLOW.is_file():
            pytest.skip("container-delivery.yml not present")

        content = _read(CONTAINER_DELIVERY_WORKFLOW)
        assert f"IMAGE_REPO: {CANONICAL_IMAGE_REPO}" in content, (
            "container-delivery.yml must publish to the canonical image "
            f"repository {CANONICAL_IMAGE_REPO}"
        )
        assert "opsswarm-openclaw-github" not in content, (
            "container-delivery.yml must not reference a stale image repository "
            "name; kustomize would silently drop the digest pin"
        )

    def test_manifests_reference_the_canonical_repository(self):
        """The base deployment must reference the canonical repository."""
        deployment = K8S_BASE / "deployment.yaml"
        if not deployment.is_file():
            pytest.skip("k8s/base/deployment.yaml not present")

        content = _read(deployment)
        images = re.findall(r"image:\s*(\S+)", content)
        assert images, "the deployment must declare container images"
        for image in images:
            assert image.startswith(CANONICAL_IMAGE_REPO), (
                f"manifest image {image!r} does not match the canonical "
                f"repository {CANONICAL_IMAGE_REPO}"
            )

    def test_overlay_digest_pin_actually_applies(self):
        """A digest pin matching the manifest image must survive rendering.

        This is the regression that the image-repository drift caused: the
        kustomize ``images`` transformer matches on the *image name*, so a
        mismatched ``name:`` silently leaves the mutable tag in place.
        """
        rendered = _render(DEV_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")

        assert ":latest" not in rendered, "the dev overlay must not reference a mutable :latest tag"
        assert CANONICAL_IMAGE_REPO in rendered, (
            "the rendered dev overlay must reference the canonical repository"
        )


# ---------------------------------------------------------------------------
# Digest assertion logic
# ---------------------------------------------------------------------------


class TestDigestAssertion:
    """The published digest must be validated before it is used as evidence."""

    def test_workflow_asserts_the_digest_shape(self):
        """The workflow must reject a malformed digest."""
        if not CONTAINER_DELIVERY_WORKFLOW.is_file():
            pytest.skip("container-delivery.yml not present")

        content = _read(CONTAINER_DELIVERY_WORKFLOW)
        assert re.search(r"\^sha256:\[a-f0-9\]\{64\}\$", content), (
            "container-delivery.yml must assert the manifest digest against ^sha256:[a-f0-9]{64}$"
        )

    def test_workflow_pulls_by_digest_not_by_tag(self):
        """Evidence must come from a digest-addressed pull."""
        if not CONTAINER_DELIVERY_WORKFLOW.is_file():
            pytest.skip("container-delivery.yml not present")

        content = _read(CONTAINER_DELIVERY_WORKFLOW)
        assert 'docker pull "$IMAGE_REF"' in content, (
            "container-delivery.yml must pull the image by its immutable digest"
        )

    @pytest.mark.parametrize(
        "digest",
        [
            "sha256:" + "0" * 64,
            "sha256:" + "a" * 64,
            "sha256:" + "f" * 64,
        ],
    )
    def test_well_formed_digests_are_accepted(self, digest):
        """The regex accepts every well-formed digest."""
        assert DIGEST_PATTERN.match(digest) is not None

    @pytest.mark.parametrize(
        "digest",
        [
            "",
            "sha256:",
            "sha256:" + "0" * 63,
            "sha256:" + "0" * 65,
            "sha256:" + "g" * 64,
            "SHA256:" + "0" * 64,
            "sha512:" + "0" * 64,
            "0" * 64,
        ],
    )
    def test_malformed_digests_are_rejected(self, digest):
        """The regex rejects every malformed digest."""
        assert DIGEST_PATTERN.match(digest) is None


# ---------------------------------------------------------------------------
# Rendered manifest policy
# ---------------------------------------------------------------------------


class TestRenderedManifestPolicy:
    """The rendered production overlay must satisfy the least-privilege policy."""

    def test_prod_overlay_renders(self):
        """The production overlay must render without errors."""
        rendered = _render(PROD_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")
        assert "kind: Deployment" in rendered

    def test_prod_overlay_has_no_broad_public_ingress(self):
        """No rendered production NetworkPolicy may allow 0.0.0.0/0 ingress."""
        rendered = _render(PROD_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")

        policies = [doc for doc in rendered.split("\n---\n") if "kind: NetworkPolicy" in doc]
        assert policies, "the production overlay must render a NetworkPolicy"
        for policy in policies:
            ingress = policy.split("ingress:", 1)
            if len(ingress) == 1:
                continue
            block = ingress[1].split("egress:")[0]
            assert "cidr: 0.0.0.0/0" not in block, (
                "the rendered production NetworkPolicy must not allow broad public ingress"
            )

    def test_prod_overlay_gates_readiness_on_ready_not_health(self):
        """Readiness must use /ready; /health is liveness only."""
        rendered = _render(PROD_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")

        assert "path: /ready" in rendered, (
            "the rendered production deployment must gate readiness on /ready"
        )

    def test_prod_overlay_persists_state_on_persistent_volume_claims(self):
        """Evidence and runtime data must be PVC-backed, not emptyDir."""
        rendered = _render(PROD_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")

        assert "persistentVolumeClaim" in rendered, (
            "the production deployment must mount persistent volume claims"
        )

    def test_prod_overlay_sets_fs_group_at_pod_level(self):
        """fsGroup belongs on the Pod spec, so every container honours it."""
        rendered = _render(PROD_OVERLAY)
        if rendered is None:
            pytest.skip("no kustomize implementation available")

        assert "fsGroup: 10001" in rendered, (
            "the production deployment must set fsGroup at Pod level"
        )

    def test_single_kubernetes_tree_only(self):
        """There must be exactly one Kubernetes tree in the repository."""
        candidates = [
            path
            for path in REPO_ROOT.iterdir()
            if path.is_dir() and path.name in {"k8s", "kubernetes", "deploy"}
        ]
        kubernetes_trees = []
        for candidate in candidates:
            if candidate.name == "deploy":
                # deploy/ holds Prometheus and systemd assets, not manifests.
                nested = candidate / "kubernetes"
                if nested.is_dir():
                    kubernetes_trees.append(nested)
                continue
            kubernetes_trees.append(candidate)

        assert len(kubernetes_trees) == 1, (
            "the repository must contain exactly one Kubernetes tree; found "
            f"{[str(p) for p in kubernetes_trees]}"
        )
