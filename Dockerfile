# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 – builder (produces wheel for reproducibility)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution (no pip install overhead)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create a virtual environment so COPY --from=builder works (uv venv, not --system)
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Upgrade base tools to address CVE-2026-XXX in setuptools/wheel bundled in python:3.11-slim
RUN uv pip install --no-cache --upgrade setuptools wheel

# Install dependencies into the venv
RUN uv pip install --no-cache \
        fastapi>=0.115 \
        pydantic>=2.9 \
        pydantic-settings>=2.6 \
        uvicorn>=0.32

# Copy source and install the package into the venv
COPY apps/api/ apps/api/
COPY data/ data/
COPY services/ services/
RUN uv pip install --no-cache -e apps/api/


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 – runtime (non-root, single layer, minimal surface)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Create a dedicated non-root user and group
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --shell /bin/false appuser

WORKDIR /app

# Copy venv (Python + installed packages) and source (editable .pth resolves here)
COPY --from=builder --chown=appuser:appgroup /app/.venv/ .venv/
COPY --from=builder --chown=appuser:appgroup /app/apps/api/ apps/api/
COPY --from=builder --chown=appuser:appgroup /app/data/ ./data/
# Cross-package utilities imported lazily by main.py:_ensure_simulation_kpi_path
# (services/simulation/kpi/evaluator.py depends on services/forecasting/risk/stockout.py).
COPY --from=builder --chown=appuser:appgroup /app/services/ services/
# Required by retailtwin_api.version — it reads the canonical SemVer at import
# time (apps/api/retailtwin_api/version.py:read_version). Without this the
# container raises InvalidVersion before uvicorn can bind the port.
COPY VERSION VERSION

# Make the venv Python/uvicorn available on PATH (base Python is outside the venv)
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8080

# Run as non-root. Cloud Run sends traffic to 0.0.0.0:$PORT.
USER appuser

EXPOSE 8080

# Docker-only check. Cloud Run uses its own HTTP probe and ignores this.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8080'))"

# exec so Cloud Run's SIGTERM reaches uvicorn. Uvicorn does not read PORT by itself.
ENTRYPOINT ["/bin/sh", "-c", "exec /app/.venv/bin/python -m uvicorn retailtwin_api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
