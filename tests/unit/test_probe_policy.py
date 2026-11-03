"""Unit tests for the positive Kubernetes probe policy.

The probe contract enforced here (ADR-030 R7, Issues #125 and #126):

* every application container declares a readinessProbe;
* the readinessProbe targets ``/ready`` — the fail-closed readiness gate;
* the readinessProbe never targets ``/health`` — a liveness signal;
* the livenessProbe targets ``/health`` and stays independent of the
  HA / Postgres gate.

The same policy is asserted by ``scripts/check_probe_policy.py``, which the
``container-delivery`` workflow runs against the rendered dev overlay.  These
tests cover each rule in turn with a fixture, so a regression fails here
before it can reach the cluster.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_probe_policy import ProbePolicyError, check_file, check_manifest


def _deployment(
    *,
    readiness_path: str | None = "/ready",
    liveness_path: str | None = "/health",
    container_name: str = "opsswarm",
) -> dict:
    container: dict = {"name": container_name, "image": "ghcr.io/example/opsswarm:2.2.0"}
    if readiness_path is not None:
        container["readinessProbe"] = {"httpGet": {"path": readiness_path, "port": 8080}}
    if liveness_path is not None:
        container["livenessProbe"] = {"httpGet": {"path": liveness_path, "port": 8080}}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "opsswarm", "namespace": "opsswarm"},
        "spec": {
            "replicas": 1,
            "template": {"spec": {"containers": [container]}},
        },
    }


def _write(tmp_path: Path, documents: list[dict]) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        yaml.safe_dump_all(documents, default_flow_style=False),
        encoding="utf-8",
    )
    return path


def test_correct_probe_configuration_passes() -> None:
    check_manifest([_deployment()])


def test_correct_probe_configuration_passes_via_file(tmp_path: Path) -> None:
    manifest = _write(tmp_path, [_deployment()])

    check_file(manifest)


def test_missing_readiness_probe_fails() -> None:
    with pytest.raises(ProbePolicyError, match="a readinessProbe is required"):
        check_manifest([_deployment(readiness_path=None)])


def test_readiness_probe_on_health_fails() -> None:
    """The 'readiness probe must not use /health' rule must stay in force."""
    with pytest.raises(ProbePolicyError, match="must not use /health"):
        check_manifest([_deployment(readiness_path="/health")])


def test_readiness_probe_on_an_unknown_path_fails() -> None:
    with pytest.raises(ProbePolicyError, match="must target /ready"):
        check_manifest([_deployment(readiness_path="/readyz")])


def test_liveness_probe_must_stay_on_health() -> None:
    with pytest.raises(ProbePolicyError, match="livenessProbe must target /health"):
        check_manifest([_deployment(liveness_path="/ready")])


def test_missing_liveness_probe_fails() -> None:
    with pytest.raises(ProbePolicyError, match="livenessProbe on /health is required"):
        check_manifest([_deployment(liveness_path=None)])


def test_manifest_without_deployment_fails() -> None:
    with pytest.raises(ProbePolicyError, match="contains no Deployment"):
        check_manifest([{"apiVersion": "v1", "kind": "Service", "metadata": {"name": "s"}}])


def test_the_shipped_base_manifest_satisfies_the_probe_policy() -> None:
    """The base manifest must satisfy the same policy the CI workflow enforces."""
    base = Path(__file__).resolve().parents[2] / "k8s" / "base" / "deployment.yaml"

    check_file(base)
