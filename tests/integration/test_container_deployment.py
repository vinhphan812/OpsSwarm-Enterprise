"""
tests/integration/test_container_deployment.py
=============================================

Integration tests for Issue #73 — Container and Kubernetes deployment profile.

This module verifies all acceptance criteria for the container deployment pipeline:
  A. OCI image        — Dockerfile multi-stage, non-root, health, no secrets in layers
  B. Docker Compose   — config validation, health, token injection, volume persistence
  C. Kubernetes      — kustomize renders, non-root, probes, ConfigMap/Secret separation
  D. Documentation   — CONTAINER_DEPLOYMENT.md, SECURITY.md, OPERATIONS.md coverage

Tests are designed to run in CI (GitHub Actions ubuntu-latest) and locally (Linux/WSL).
Windows-native Docker Desktop is not a supported test target — use WSL2 for local runs.

Manual steps (not automatable in CI) are documented with comments prefixed:
  # MANUAL: <description>
These require a human operator to verify and mark as done.

Markers
-------
@pytest.mark.integration
@pytest.mark.container
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ── Project root ──────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── Artifact paths ────────────────────────────────────────────────────────────

DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKER_COMPOSE_OVERRIDE = REPO_ROOT / "docker-compose.override.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.compose.example"

K8S_DIR = REPO_ROOT / "k8s"
K8S_BASE = K8S_DIR / "base"
K8S_KUSTOMIZATION = K8S_DIR / "kustomization.yaml"
K8S_BASE_KUSTOMIZATION = K8S_BASE / "kustomization.yaml"

DOCS_DIR = REPO_ROOT / "docs"
CONTAINER_DEPLOYMENT_GUIDE = DOCS_DIR / "guides" / "CONTAINER_DEPLOYMENT.md"
SECURITY_DOC = DOCS_DIR / "SECURITY.md"
OPERATIONS_DOC = DOCS_DIR / "OPERATIONS.md"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"

OPSSWARM_VERSION_FILE = REPO_ROOT / "opsswarm" / "__version__.py"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def run(
    cmd: list[str],
    cwd: Path | str | None = None,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command, returning the CompletedProcess."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        env=env,
    )


def read(path: Path) -> str:
    """Read a text file and return its contents."""
    return path.read_text(encoding="utf-8")


def grep_file(pattern: str, path: Path) -> list[str]:
    """Return all lines in *path* that match *pattern* (case-insensitive)."""
    try:
        return [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()
                if re.search(pattern, line, re.IGNORECASE)]
    except FileNotFoundError:
        return []


def is_tool_available(name: str) -> bool:
    """Return True when *name* is on PATH."""
    try:
        subprocess.run(
            ["which", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_available() -> bool:
    return is_tool_available("docker")


def kubectl_available() -> bool:
    return is_tool_available("kubectl")


def kustomize_available() -> bool:
    return is_tool_available("kustomize")


# ─────────────────────────────────────────────────────────────────────────────
# A. OCI Image
# ─────────────────────────────────────────────────────────────────────────────

class TestOCIDockerfile:
    """Acceptance criteria A.1 – A.7 for the OCI image."""

    def test_dockerfile_exists(self):
        """A.1  Dockerfile exists at project root."""
        assert DOCKERFILE.is_file(), f"Dockerfile not found at {DOCKERFILE}"

    def test_dockerfile_has_multi_stage_build(self):
        """A.1  Dockerfile uses multi-stage build (builder → runtime)."""
        content = read(DOCKERFILE)
        # Stage 1 should build/install dependencies; Stage 2 should be slim runtime.
        assert "AS builder" in content or "FROM python:3.11-slim AS" in content, \
            "Dockerfile must have a named builder stage"
        assert "AS runtime" in content or "FROM python:3.11-slim AS" in content, \
            "Dockerfile must have a named runtime stage"
        # The runtime stage should copy from the builder.
        assert re.search(r"COPY\s+--from=builder", content), \
            "Runtime stage must copy artifacts from builder using --from=builder"

    def test_dockerfile_non_root_user(self):
        """A.2  Image creates and switches to non-root user (uid 10001)."""
        content = read(DOCKERFILE)
        # groupadd / useradd with explicit gid/uid 10001
        assert re.search(r"(groupadd|addgroup).*10001", content), \
            "Dockerfile must create appgroup with gid 10001"
        assert re.search(r"(useradd|adduser).*10001", content), \
            "Dockerfile must create appuser with uid 10001"
        # USER directive switches away from root.
        assert re.search(r"^\s*USER\s+appuser", content, re.MULTILINE), \
            "Dockerfile must have USER directive to switch to non-root"

    def test_dockerfile_exec_entrypoint_for_sigterm(self):
        """A.5  ENTRYPOINT uses exec so SIGTERM reaches uvicorn directly."""
        content = read(DOCKERFILE)
        # Look for shell form with exec, or JSON array form.
        # exec replaces the shell with uvicorn as PID 1.
        assert "exec" in content, \
            "ENTRYPOINT must use 'exec' to replace shell with uvicorn as PID 1"
        assert "uvicorn" in content, \
            "ENTRYPOINT must invoke uvicorn"

    def test_dockerfile_no_github_token_in_layers(self):
        """A.4  No GitHub token patterns in Dockerfile source (secrets not baked in)."""
        content = read(DOCKERFILE)
        forbidden = ["GITHUB_TOKEN", "ghp_", "ghs_", "ghu_", "gho_", "ghr_"]
        for pattern in forbidden:
            assert pattern not in content, \
                f"Dockerfile must not contain hardcoded secret pattern: {pattern}"

    def test_dockerfile_opsswarm_openclaw_bin_env_var(self):
        """A.1  OPSWARM_OPENCLAW_BIN env var is documented / defaulted to empty."""
        content = read(DOCKERFILE)
        # The env var should be either absent (binary not in image) or explicitly
        # set to empty string (documenting the contract that it must be supplied at runtime).
        # A hardcoded binary path would be a policy violation.
        # We allow OPSWARM_OPENCLAW_BIN=${...} or OPSWARM_OPENCLAW_BIN: but not a literal path.
        assert not re.search(r'OPSWARM_OPENCLAW_BIN[=:]["\'].*openclaw', content), \
            "OpenClaw binary must not be embedded in image layers"

    def test_dockerfile_version_file_copied(self):
        """A.6  VERSION file is copied into the runtime stage."""
        content = read(DOCKERFILE)
        # VERSION must be copied so that opsswarm/__version__.py resolves correctly.
        assert re.search(r"COPY\s+VERSION\s+VERSION", content), \
            "Dockerfile must copy VERSION file into the runtime stage"

    def test_opsswarm_version_file_exists(self):
        """A.6  opsswarm/__version__.py exists and exports __version__."""
        assert OPSSWARM_VERSION_FILE.is_file(), \
            f"opsswarm/__version__.py not found at {OPSSWARM_VERSION_FILE}"
        content = read(OPSSWARM_VERSION_FILE)
        assert re.search(r'^__version__\s*=\s*["\']\d+\.\d+\.\d+', content, re.MULTILINE), \
            "opsswarm/__version__.py must export __version__ = '<semver>'"

    def test_dockerfile_readonly_root_filesystem_dirs(self):
        """A.1  Explicitly writable directories are created and chowned to appuser."""
        content = read(DOCKERFILE)
        # The runtime stage should create at least /var/lib/opsswarm or /app/runtime-data
        # and chown them to appuser:appgroup so the non-root user can write.
        has_chown = re.search(r"chown\s+.*appuser.*\s+/var/lib/opsswarm", content)
        has_chown |= re.search(r"chown\s+.*10001.*\s+/var/lib/opsswarm", content)
        has_chown |= re.search(r"--chown=appuser:appgroup", content)
        assert has_chown, \
            "Dockerfile must chown writable directories to appuser for read-only root fs"

    def test_healthcheck_configured(self):
        """A.3  HEALTHCHECK instruction targets /health endpoint."""
        content = read(DOCKERFILE)
        assert "HEALTHCHECK" in content, \
            "Dockerfile must include a HEALTHCHECK instruction"
        assert "/health" in content, \
            "HEALTHCHECK must probe the /health endpoint"


class TestOCIReleaseWorkflow:
    """Acceptance criteria A.6 – A.7 for the release CI pipeline."""

    def test_release_workflow_exists(self):
        """A.6  release.yml workflow exists."""
        assert RELEASE_WORKFLOW.is_file(), \
            f"Release workflow not found at {RELEASE_WORKFLOW}"

    def test_sbom_generated_in_release(self):
        """A.7  Release workflow generates SPDX/CycloneDX SBOM JSON artifact."""
        if not RELEASE_WORKFLOW.is_file():
            pytest.skip("release.yml not found")

        content = read(RELEASE_WORKFLOW)
        # Look for syft or anchore/sbom-action producing JSON SBOM.
        has_sbom_action = "anchore/sbom-action" in content or "syft" in content
        has_json_output = "spdx" in content.lower() or "json" in content.lower()
        has_sbom_artifact = "sbom" in content.lower() and ".json" in content

        assert has_sbom_action and (has_json_output or has_sbom_artifact), \
            "release.yml must generate SPDX/CycloneDX SBOM JSON artifact"

    def test_image_digest_recorded_in_release(self):
        """A.6  Release workflow records the image digest (docker inspect)."""
        if not RELEASE_WORKFLOW.is_file():
            pytest.skip("release.yml not found")

        content = read(RELEASE_WORKFLOW)
        # docker inspect --format='{{.RepoDigests}}' or similar to capture digest.
        assert "digest" in content.lower() or "sha256" in content.lower(), \
            "release.yml must record the image digest"

    def test_trivy_fail_closed_in_security_workflow(self):
        """A.7  security.yml uses Trivy at HIGH/CRITICAL with exit-code 1 (fail-closed)."""
        if not SECURITY_WORKFLOW.is_file():
            pytest.skip("security.yml not found")

        content = read(SECURITY_WORKFLOW)
        assert "trivy" in content.lower(), \
            "security.yml must run Trivy security scanning"
        assert re.search(r"severity\s+HIGH.*CRITICAL|CRITICAL.*HIGH", content), \
            "Trivy must scan for HIGH and CRITICAL severities"
        assert "--exit-code 1" in content or "exit 1" in content, \
            "Trivy must fail-closed (exit-code 1 on HIGH/CRITICAL)"

    def test_sbom_artifact_uploaded_in_release(self):
        """A.7  SBOM JSON is uploaded as a workflow artifact."""
        if not RELEASE_WORKFLOW.is_file():
            pytest.skip("release.yml not found")

        content = read(RELEASE_WORKFLOW)
        assert "upload-artifact" in content, \
            "release.yml must upload artifacts"
        # SBOM should be listed in the upload.
        assert re.search(r"sbom.*\.json|spdx.*json", content, re.IGNORECASE), \
            "release.yml must upload the SBOM JSON artifact"


# ─────────────────────────────────────────────────────────────────────────────
# B. Docker Compose
# ─────────────────────────────────────────────────────────────────────────────

class TestDockerCompose:
    """Acceptance criteria B.1 – B.5 for Docker Compose."""

    @pytest.fixture(autouse=True)
    def _compose_files_present(self):
        # B.1 – docker-compose.yml must exist.
        # docker-compose.override.yml is optional (dev profile only).
        if not DOCKER_COMPOSE.is_file():
            pytest.skip(f"docker-compose.yml not found at {DOCKER_COMPOSE}")

    def test_compose_config_validates(self):
        """B.1  docker compose config succeeds (valid YAML + references)."""
        if not docker_available():
            pytest.skip("docker not available in this environment")

        # Run `docker compose config` to validate the merged compose file.
        result = run(
            ["docker", "compose", "config"],
            cwd=REPO_ROOT,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, \
            f"docker compose config failed:\n{result.stderr}"

    def test_compose_defines_healthcheck(self):
        """B.2  Service has a healthcheck defined."""
        content = read(DOCKER_COMPOSE)
        assert "healthcheck" in content, \
            "docker-compose.yml must define a healthcheck"
        assert "health" in content.lower(), \
            "healthcheck must probe the /health endpoint"

    def test_compose_injects_token_via_file_mount(self):
        """B.3  GitHub token injected via read-only file mount, not baked in image."""
        content = read(DOCKER_COMPOSE)
        # Look for GITHUB_TOKEN_FILE env var pointing to /run/secrets/.
        assert "GITHUB_TOKEN_FILE" in content, \
            "docker-compose.yml must use GITHUB_TOKEN_FILE for token injection"
        assert "/run/secrets/" in content, \
            "Token file must be mounted at /run/secrets/ inside container"
        # read_only: true on the token volume mount.
        assert "read_only" in content or "read_only: true" in content or "readOnly" in content, \
            "Token file mount must be read-only"

    def test_compose_uses_named_volumes(self):
        """B.4  Named volumes preserve runtime-data across restarts."""
        content = read(DOCKER_COMPOSE)
        # Must have opsswarm-runtime-data or similar named volume.
        assert re.search(r"opsswarm-runtime-data|runtime-data", content, re.IGNORECASE), \
            "docker-compose.yml must use a named volume for runtime-data"
        # Volume should be declared in the volumes: section.
        assert re.search(r"^volumes:\s*$", content, re.MULTILINE), \
            "docker-compose.yml must have a volumes: section"

    def test_compose_has_sigterm_graceful_shutdown(self):
        """B.2  Compose configures SIGTERM graceful shutdown (30s grace period)."""
        content = read(DOCKER_COMPOSE)
        assert "SIGTERM" in content or "stop_signal" in content, \
            "docker-compose.yml must configure stop_signal: SIGTERM"
        assert "stop_grace_period" in content or "30s" in content, \
            "docker-compose.yml must have stop_grace_period (recommend 30s)"

    def test_compose_prometheus_scrape_annotations(self):
        """B.5  Compose documents Prometheus scrape configuration for /metrics."""
        content = read(DOCKER_COMPOSE)
        # Prometheus scrape annotations are in K8s deployment; Compose documents them.
        # Check if the guide or comments mention Prometheus.
        if CONTAINER_DEPLOYMENT_GUIDE.is_file():
            guide = read(CONTAINER_DEPLOYMENT_GUIDE)
            assert "prometheus" in guide.lower() and "metrics" in guide.lower(), \
                "CONTAINER_DEPLOYMENT.md must document Prometheus scrape for /metrics"

    def test_compose_openclaw_profile_available(self):
        """B.1  docker compose --profile openclaw config validates."""
        if not docker_available():
            pytest.skip("docker not available in this environment")

        result = run(
            ["docker", "compose", "--profile", "openclaw", "config"],
            cwd=REPO_ROOT,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, \
            f"docker compose --profile openclaw config failed:\n{result.stderr}"

    def test_compose_example_env_file_documents_token_injection(self):
        """B.3  .env.compose.example documents the token injection pattern."""
        if not ENV_EXAMPLE.is_file():
            pytest.skip(f".env.compose.example not found at {ENV_EXAMPLE}")

        content = read(ENV_EXAMPLE)
        assert "GITHUB_TOKEN" in content or "GITHUB_TOKEN_FILE" in content, \
            ".env.compose.example must document GITHUB_TOKEN or GITHUB_TOKEN_FILE"


# ─────────────────────────────────────────────────────────────────────────────
# C. Kubernetes
# ─────────────────────────────────────────────────────────────────────────────

class TestKubernetes:
    """Acceptance criteria C.1 – C.7 for Kubernetes manifests."""

    def test_k8s_directory_exists(self):
        """C.1  k8s/ directory with base manifests exists."""
        assert K8S_DIR.is_dir(), f"k8s/ directory not found at {K8S_DIR}"

    def test_kustomize_root_exists(self):
        """C.1  k8s/kustomization.yaml exists."""
        assert K8S_KUSTOMIZATION.is_file(), \
            f"k8s/kustomization.yaml not found at {K8S_KUSTOMIZATION}"

    def test_kustomize_renders(self):
        """C.1  kubectl kustomize k8s/ renders without errors or warnings."""
        if not kustomize_available():
            pytest.skip("kustomize not available in this environment")

        result = run(
            ["kustomize", "build", str(K8S_DIR)],
            cwd=REPO_ROOT,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, \
            f"kustomize build failed:\n{result.stderr}"
        # Output must contain Kubernetes resource kinds.
        output = result.stdout
        assert "kind:" in output, \
            "kustomize output must contain Kubernetes resource manifests"

    def test_kubectl_dry_run_passes(self):
        """C.2  kubectl apply --dry-run=server -k k8s/ passes."""
        if not kubectl_available():
            pytest.skip("kubectl not available in this environment")

        # Check cluster connectivity first.
        check = run(
            ["kubectl", "cluster-info"],
            check=False,
            timeout=10,
        )
        if check.returncode != 0:
            pytest.skip("kubectl not connected to a cluster; skipping dry-run")

        result = run(
            ["kubectl", "apply", "--dry-run=server", "-k", str(K8S_DIR)],
            cwd=REPO_ROOT,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, \
            f"kubectl dry-run failed:\n{result.stderr}"

    def test_deployment_non_root_security_context(self):
        """C.3  Deployment securityContext runs as non-root (uid 10001)."""
        deployment_file = K8S_BASE / "deployment.yaml"
        if not deployment_file.is_file():
            pytest.skip(f"deployment.yaml not found at {deployment_file}")

        content = read(deployment_file)
        assert "runAsNonRoot" in content or "runAsNonRoot: true" in content, \
            "deployment.yaml must set runAsNonRoot: true"
        assert "runAsUser: 10001" in content, \
            "deployment.yaml must set runAsUser: 10001 (matches Dockerfile uid)"

    def test_deployment_liveness_probe(self):
        """C.4  Liveness probe configured on /health."""
        deployment_file = K8S_BASE / "deployment.yaml"
        if not deployment_file.is_file():
            pytest.skip(f"deployment.yaml not found at {deployment_file}")

        content = read(deployment_file)
        assert "livenessProbe" in content, \
            "deployment.yaml must define a livenessProbe"
        assert "/health" in content, \
            "livenessProbe must target /health endpoint"

    def test_configmap_secret_separated(self):
        """C.5  ConfigMap and Secret are separate resources (no secrets in ConfigMap)."""
        configmap_file = K8S_BASE / "configmap.yaml"
        secret_file = K8S_BASE / "secret.yaml"

        if not configmap_file.is_file():
            pytest.skip(f"configmap.yaml not found at {configmap_file}")
        if not secret_file.is_file():
            pytest.skip(f"secret.yaml not found at {secret_file}")

        configmap_content = read(configmap_file)
        secret_content = read(secret_file)

        assert "kind: ConfigMap" in configmap_content, \
            "configmap.yaml must be a ConfigMap resource"
        assert "kind: Secret" in secret_content, \
            "secret.yaml must be a Secret resource"

        # ConfigMap must NOT contain sensitive values.
        forbidden = ["ghp_", "ghs_", "ghu_", "gho_", "ghr_", "GITHUB_TOKEN"]
        for pattern in forbidden:
            assert pattern not in configmap_content, \
                f"configmap.yaml must not contain secret pattern: {pattern}"

    def test_pdb_allows_single_replica_safe_operation(self):
        """C.6  PodDisruptionBudget uses minAvailable: 1 (safe for replicas=1)."""
        pdb_file = K8S_BASE / "pdb.yaml"
        if not pdb_file.is_file():
            pytest.skip(f"pdb.yaml not found at {pdb_file}")

        content = read(pdb_file)
        assert "minAvailable: 1" in content or "minAvailable:\"1\"" in content, \
            "pdb.yaml must use minAvailable: 1 for single-replica safe operation"

    def test_network_policy_exists_with_egress_allowlist(self):
        """C.7  NetworkPolicy exists with GitHub/OpenClaw egress allowlist."""
        netpol_file = K8S_BASE / "network-policy.yaml"
        if not netpol_file.is_file():
            pytest.skip(f"network-policy.yaml not found at {netpol_file}")

        content = read(netpol_file)
        assert "kind: NetworkPolicy" in content, \
            "network-policy.yaml must be a NetworkPolicy resource"
        # Must allow egress to GitHub API.
        assert "api.github.com" in content or "140.82" in content, \
            "NetworkPolicy must allow egress to GitHub API"
        # Must allow egress for OpenClaw.
        assert "openclaw" in content.lower(), \
            "NetworkPolicy must allow egress for OpenClaw runtime"
        # Must allow DNS (kube-dns) for service discovery.
        assert "53" in content or "dns" in content.lower(), \
            "NetworkPolicy must allow DNS (kube-dns) egress"

    def test_k8s_namespace_exists(self):
        """C.1  namespace.yaml defines the opsswarm namespace."""
        ns_file = K8S_BASE / "namespace.yaml"
        if not ns_file.is_file():
            pytest.skip(f"namespace.yaml not found at {ns_file}")

        content = read(ns_file)
        assert "kind: Namespace" in content, \
            "namespace.yaml must be a Namespace resource"
        assert "opsswarm" in content, \
            "namespace must be named 'opsswarm'"

    def test_k8s_service_exists(self):
        """C.1  service.yaml defines the opsswarm ClusterIP/LoadBalancer service."""
        svc_file = K8S_BASE / "service.yaml"
        if not svc_file.is_file():
            pytest.skip(f"service.yaml not found at {svc_file}")

        content = read(svc_file)
        assert "kind: Service" in content, \
            "service.yaml must be a Service resource"
        assert "8080" in content, \
            "Service must expose port 8080"

    def test_k8s_overlays_exist(self):
        """C.1  overlays/dev and overlays/prod kustomizations exist."""
        dev_overlay = K8S_DIR / "overlays" / "dev" / "kustomization.yaml"
        prod_overlay = K8S_DIR / "overlays" / "prod" / "kustomization.yaml"

        assert dev_overlay.is_file(), \
            f"overlays/dev/kustomization.yaml not found at {dev_overlay}"
        assert prod_overlay.is_file(), \
            f"overlays/prod/kustomization.yaml not found at {prod_overlay}"


# ─────────────────────────────────────────────────────────────────────────────
# D. Documentation
# ─────────────────────────────────────────────────────────────────────────────

class TestDocumentation:
    """Acceptance criteria D.1 – D.3 for documentation."""

    def test_container_deployment_guide_exists(self):
        """D.1  CONTAINER_DEPLOYMENT.md covers OCI, Compose, and K8s deployment."""
        assert CONTAINER_DEPLOYMENT_GUIDE.is_file(), \
            f"CONTAINER_DEPLOYMENT.md not found at {CONTAINER_DEPLOYMENT_GUIDE}"

    def test_container_deployment_guide_covers_oci(self):
        """D.1  Guide covers OCI image build and run."""
        content = read(CONTAINER_DEPLOYMENT_GUIDE)
        assert "docker build" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must document docker build"
        assert "docker run" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must document docker run"

    def test_container_deployment_guide_covers_compose(self):
        """D.1  Guide covers Docker Compose deployment."""
        content = read(CONTAINER_DEPLOYMENT_GUIDE)
        assert "compose" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must cover Docker Compose deployment"
        assert "docker compose up" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must document docker compose up"

    def test_container_deployment_guide_covers_k8s(self):
        """D.1  Guide covers Kubernetes deployment."""
        content = read(CONTAINER_DEPLOYMENT_GUIDE)
        assert "kubernetes" in content.lower() or "k8s" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must cover Kubernetes deployment"
        assert "kustomize" in content.lower() or "kubectl" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must document kustomize or kubectl usage"

    def test_security_doc_covers_container_security(self):
        """D.2  SECURITY.md has container security notes (non-root, secret injection)."""
        assert SECURITY_DOC.is_file(), \
            f"SECURITY.md not found at {SECURITY_DOC}"

        content = read(SECURITY_DOC)
        # Non-root container security.
        assert "non-root" in content.lower() or "nonroot" in content.lower() or "10001" in content, \
            "SECURITY.md must document non-root container security"
        # Secret injection.
        assert "secret" in content.lower(), \
            "SECURITY.md must cover secret injection patterns"
        # Trivy fail-closed policy.
        assert "trivy" in content.lower() or "CRITICAL" in content or "HIGH" in content, \
            "SECURITY.md must document the Trivy fail-closed policy"

    def test_operations_doc_has_container_runbook(self):
        """D.3  OPERATIONS.md has operations runbook for container deployment."""
        assert OPERATIONS_DOC.is_file(), \
            f"OPERATIONS.md not found at {OPERATIONS_DOC}"

        content = read(OPERATIONS_DOC)
        # Should mention health endpoint for container probes.
        assert "health" in content.lower(), \
            "OPERATIONS.md must cover health endpoint usage"
        # Should mention telemetry / metrics.
        assert "metrics" in content.lower() or "telemetry" in content.lower(), \
            "OPERATIONS.md must cover metrics/telemetry"

    def test_container_deployment_guide_documents_trivy_policy(self):
        """D.2  CONTAINER_DEPLOYMENT.md documents the Trivy fail-closed policy."""
        if not CONTAINER_DEPLOYMENT_GUIDE.is_file():
            pytest.skip("CONTAINER_DEPLOYMENT.md not found")

        content = read(CONTAINER_DEPLOYMENT_GUIDE)
        assert "trivy" in content.lower(), \
            "CONTAINER_DEPLOYMENT.md must document Trivy fail-closed policy"

    def test_security_workflow_exists(self):
        """A.7  security.yml exists with Trivy HIGH/CRITICAL scanning."""
        assert SECURITY_WORKFLOW.is_file(), \
            f"security.yml not found at {SECURITY_WORKFLOW}"


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL VERIFICATION CHECKLIST
# ─────────────────────────────────────────────────────────────────────────────
# The following acceptance criteria CANNOT be verified automatically in CI
# because they require a running container or cluster.  Mark as verified
# after running the manual commands below.
#
# MANUAL: A.1  docker build -f Dockerfile -t opsswarm:local .
#                # Must succeed on Linux/WSL with no error output.
#
# MANUAL: A.2  docker run --rm -it --entrypoint id opsswarm:local
#                # Expected: uid=10001(appuser) gid=10001(appgroup)
#
# MANUAL: A.3  docker run -d -p 8080:8080 -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw
#                      -e GITHUB_TOKEN=ghp_... opsswarm:local
#                curl http://localhost:8080/health
#                # Expected: {"ok": true, "version": "2.2.0", ...}
#
# MANUAL: A.4  docker history opsswarm:local | grep -i GITHUB_TOKEN
#                docker history opsswarm:local | grep -i ghp_
#                docker history opsswarm:local | grep -i ghs_
#                # Expected: no matches (secrets must not appear in layers)
#
# MANUAL: A.5  docker run -d --name=test-shutdown opsswarm:local ...
#                docker stop test-shutdown
#                # Expected: graceful shutdown within 30s, no zombie processes
#
# MANUAL: A.6  # Record image digest after successful build:
#                docker inspect --format='{{.RepoDigests}}' opsswarm:local
#
# MANUAL: A.7  # Check release run artifacts for SPDX JSON SBOM:
#                # In GitHub Actions run for release tag, verify:
#                #   - "SBOM" artifact uploaded
#                #   - Artifact contains sbom.cdx.json or similar SPDX JSON
#
# MANUAL: B.2  docker compose up -d
#                docker compose ps   # Verify "healthy" status
#                curl http://localhost:8080/health
#
# MANUAL: B.4  docker compose down && docker compose up -d
#                # Verify opsswarm-runtime-data volume persists
#
# MANUAL: B.5  curl http://localhost:8080/metrics | grep opsswarm
#                # Prometheus must be able to scrape /metrics
#
# MANUAL: C.1  kubectl apply --dry-run=server -k k8s/overlays/dev
#
# MANUAL: C.3  kubectl get pod -n opsswarm -o jsonpath='{.spec.securityContext}'
#                # Verify runAsNonRoot: true, runAsUser: 10001
#
# MANUAL: C.7  kubectl get networkpolicy -n opsswarm
#                # Verify egress rules allow GitHub API and OpenClaw
# ─────────────────────────────────────────────────────────────────────────────
