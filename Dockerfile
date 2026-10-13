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

# Install dependencies into the venv
RUN uv pip install --no-cache \
        fastapi>=0.115 \
        pydantic>=2.9 \
        pydantic-settings>=2.6 \
        uvicorn>=0.32

# Copy source and install the package into the venv
COPY apps/api/ apps/api/
COPY data/ data/
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

# Make the venv Python/uvicorn available on PATH (base Python is outside the venv)
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8080
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=8080

# Run as non-root; uvicorn does not require root to bind a low port once
# the binary has CAP_NET_BIND_SERVICE (Python's built-in servers hold it).
USER appuser

EXPOSE 8080

# Health-check: Cloud Run probes /health every few seconds. Match the route
# so the container stays live even if the fixture is missing (returns "degraded").
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Entrypoint: use the venv Python directly so it always resolves the venv site-packages.
# Cloud Run sets PORT; uvicorn reads it from the environment.
ENTRYPOINT ["/app/.venv/bin/python", "-m", "uvicorn", "retailtwin_api.main:app"]
