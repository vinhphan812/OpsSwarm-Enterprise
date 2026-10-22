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
