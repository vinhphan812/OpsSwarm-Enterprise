# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# OpsSwarm Enterprise — OCI image
#
# Build:  docker build -f Dockerfile -t opsswarm:latest .
# Run:    docker run --read-only --tmpfs /tmp:rw --tmpfs /var/run:rw \
#              -p 8080:8080 opsswarm:latest
#
# Decision record (issue #73):
#   The legacy Dockerfile (now Dockerfile.retailtwin) built the retailtwin_api
#   microservice and is preserved for backward compatibility.  This file is the
#   canonical, production-grade container for OpsSwarm Enterprise.
#
#   OpenClaw (the AI reasoning runtime) is NOT embedded in the image layers.
#   Set OPSWARM_OPENCLAW_BIN to the path of the OpenClaw binary on the host or
#   in a Kubernetes sidecar volume at runtime.  See docs/guides/CONTAINER_DEPLOYMENT.md.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder
# Produces a reproducible wheel using locked dependencies.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast, deterministic dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create a virtual environment (not --system) so the runtime stage can copy it.
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Upgrade base tooling before installing anything else.
# build is required to produce the wheel; it is not installed by default in python:3.11-slim.
RUN uv pip install --no-cache --upgrade setuptools wheel pip build

# Install all runtime dependencies from the locked requirements file so that
# syft/Trivy can produce an accurate SBOM and vulnerability report.
COPY requirements.lock /app/requirements.lock
RUN uv pip install --no-cache -r /app/requirements.lock || \
    { echo "ERROR: failed to install from requirements.lock — dependency graph is not reproducible"; exit 1; }

# Copy source and build the wheel in-place (editable install not needed in the wheel).
#
# Only files that exist in the repository are copied.  The previous revision
# also copied `VERSION`, `apps/`, `services/` and `data/`, none of which exist
# in the tree, so `docker build` failed with "file not found" and no image
# could ever be produced or pushed to a registry.
COPY pyproject.toml /app/pyproject.toml
COPY opsswarm /app/opsswarm
COPY config /app/config
COPY scripts /app/scripts

RUN uv pip install --no-cache -e /app

# Build wheel into a staging directory so the runtime stage can copy only it.
RUN python -m build --wheel --outdir /dist /app

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# Minimal image: Python stdlib + the opsswarm wheel only.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as non-root with a fixed, unprivileged UID/GID.
# UID/GID 10001 avoids collisions with host numeric users (which typically start
# at 1000 on developer machines and 500 in containers).
RUN groupadd --gid 10001 --non-unique appgroup \
    && useradd --uid 10001 --gid appgroup --shell /bin/false --home /nonexistent appuser

WORKDIR /app

# Create the state directories that OpsSwarm requires at runtime.
#
# /var/lib/opsswarm  — the ONE writable state root.  OPSWARM_DATA_DIR points
#                      here, so RunStore writes /var/lib/opsswarm/runs/*.json
#                      and EvidenceStore writes /var/lib/opsswarm/evidence/*.jsonl.
#                      Both subdirectories live under the same durable volume so
#                      a single mount satisfies the whole state contract.
# /tmp                — scratch space for atomic-write temp files.
#
# All owned by appuser so the non-root container can write them on a
# read-only root filesystem (bind-mount or tmpfs at runtime if needed).
RUN mkdir -p /var/lib/opsswarm/runs /var/lib/opsswarm/evidence /tmp \
    && chown -R appuser:appgroup /var/lib/opsswarm

# Copy the wheel from the builder stage.
COPY --from=builder /dist/*.whl /app/

# Copy uv so we can install the wheel into a venv without pip.
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Copy config directory — opsswarm/config.py reads config/production.yaml at import time
# (before uvicorn binds the port). Without this the container raises FileNotFoundError.
# Chown so non-root appuser can read the files.
COPY --from=builder --chown=appuser:appgroup /app/config/ /app/config/

# Install the wheel into a fresh virtual environment.
# This keeps the runtime image surface minimal — no editable installs, no source.
RUN uv venv /app/.venv \
    && uv pip install --no-cache /app/*.whl \
    && rm /app/*.whl

# Expose the port that uvicorn binds (controlled by PORT env var, default 8080).
ENV PORT=8080
ENV PATH="/app/.venv/bin:$PATH"
# OPSWARM_OPENCLAW_BIN: absolute path to the OpenClaw binary.  OpsSwarm loads this
# from the environment at startup; it is NOT baked into the image layers so that
# OpenClaw can be upgraded independently of the OpsSwarm image (sidecar or host
# mount).  See docs/guides/CONTAINER_DEPLOYMENT.md.
ENV OPSWARM_OPENCLAW_BIN=""

# Verify the health endpoint responds before marking the container healthy.
# HEALTHCHECK is for `docker run` invocations only; Kubernetes probes are
# configured via the deployment manifest (separate task).
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD /app/.venv/bin/python -c \
        "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8080'))"

USER appuser

EXPOSE 8080

# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT — graceful SIGTERM
#
# Kubernetes and Docker both send SIGTERM on `kubectl delete pod` / `docker stop`.
# We use exec-form so the signal is delivered directly to PID 1 (uvicorn).
# The shell wrapper is only needed to expand ${PORT}; once exec runs, the
# shell is replaced by uvicorn and signals reach it without translation.
#
# Termination timeout: Kubernetes and Docker both default to 30 s.  If the
# application needs longer (e.g. for in-flight requests to complete), set
# the --graceful-shutdown-timeout flag on uvicorn or configure the pod's
# terminationGracePeriodSeconds in the deployment manifest.
# ─────────────────────────────────────────────────────────────────────────────
ENTRYPOINT ["/bin/sh", "-c", "exec /app/.venv/bin/python -m uvicorn opsswarm.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
