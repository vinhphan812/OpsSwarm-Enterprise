from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_manifests import ManifestValidationError, PROFILES, validate_manifest_file


def _write_manifest(path: Path, *, replicas: int = 1, readiness_path: str = "/ready") -> Path:
    path.write_text(
        f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opsswarm
  namespace: opsswarm
spec:
  replicas: {replicas}
  strategy:
    type: Recreate
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        fsGroup: 10001
      containers:
        - name: app
          image: ghcr.io/example/opsswarm:2.2.0
          securityContext:
            runAsNonRoot: true
            runAsUser: 10001
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            seccompProfile:
              type: RuntimeDefault
            capabilities:
              drop: [ALL]
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 100m
              memory: 128Mi
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
          readinessProbe:
            httpGet:
              path: {readiness_path}
              port: 8080
          volumeMounts:
            - name: runtime
              mountPath: /var/lib/opsswarm
      volumes:
        - name: runtime
          persistentVolumeClaim:
            claimName: opsswarm-runtime-data
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opsswarm-runtime-data
  namespace: opsswarm
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_valid_rendered_prod_manifest_passes(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "prod.yaml")

    assert validate_manifest_file(manifest) == []


def test_profile_can_be_selected_explicitly(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "dev.yaml")

    assert validate_manifest_file(manifest, PROFILES["dev"]) == []


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"replicas": 2}, "exactly 1 replica"),
        ({"readiness_path": "/health"}, "must not use /health"),
    ],
)
def test_manifest_policy_violations_fail_closed(
    tmp_path: Path, kwargs: dict[str, object], expected_error: str
) -> None:
    manifest = _write_manifest(tmp_path / "invalid.yaml", **kwargs)

    with pytest.raises(ManifestValidationError, match=expected_error):
        validate_manifest_file(manifest)


def _write_network_policy(path: Path, *, namespace: str = "opsswarm", cidr: str = "10.0.0.0/16", except_list: list[str] | None = None) -> Path:
    except_yaml = ""
    if except_list is not None:
        except_items = "\n".join(f"              - {exc}" for exc in except_list)
        except_yaml = f"            except:\n{except_items}"
    path.write_text(
        f"""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: test-netpol
  namespace: {namespace}
spec:
  podSelector:
    matchLabels:
      app: opsswarm
  egress:
    - to:
        - ipBlock:
            cidr: {cidr}
{except_yaml}
      ports:
        - protocol: TCP
          port: 443
""".strip(),
        encoding="utf-8",
    )
    return path


def test_valid_network_policy_passes(tmp_path: Path) -> None:
    manifest = _write_network_policy(tmp_path / "netpol.yaml", cidr="10.0.0.0/16", except_list=["10.0.1.0/24"])
    assert validate_manifest_file(manifest) == []


def test_network_policy_invalid_namespace_fails(tmp_path: Path) -> None:
    manifest = _write_network_policy(tmp_path / "netpol.yaml", namespace="default")
    with pytest.raises(ManifestValidationError, match="NetworkPolicy namespace must be 'opsswarm'"):
        validate_manifest_file(manifest)


def test_network_policy_disjoint_except_fails(tmp_path: Path) -> None:
    manifest = _write_network_policy(tmp_path / "netpol.yaml", cidr="140.82.112.0/22", except_list=["192.30.252.0/22"])
    with pytest.raises(ManifestValidationError, match="ipBlock except '192.30.252.0/22' must be a strict subset"):
        validate_manifest_file(manifest)


def test_network_policy_equal_except_fails(tmp_path: Path) -> None:
    manifest = _write_network_policy(tmp_path / "netpol.yaml", cidr="10.0.0.0/16", except_list=["10.0.0.0/16"])
    with pytest.raises(ManifestValidationError, match="ipBlock except '10.0.0.0/16' must be a strict subset"):
        validate_manifest_file(manifest)


def test_network_policy_invalid_cidr_fails(tmp_path: Path) -> None:
    manifest = _write_network_policy(tmp_path / "netpol.yaml", cidr="not-a-cidr")
    with pytest.raises(ManifestValidationError, match="invalid cidr"):
        validate_manifest_file(manifest)
