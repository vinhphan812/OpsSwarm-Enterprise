# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY requirements.txt requirements.lock ./
COPY opsswarm/ ./opsswarm/

# Build wheel using pip and requirements.lock hashes
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python -m build --wheel --no-isolation

FROM python:3.11-slim AS runtime

WORKDIR /app

RUN groupadd -g 10001 opsswarm && \
    useradd -u 10001 -g opsswarm -m -s /bin/bash opsswarm && \
    mkdir -p /var/lib/opsswarm && \
    chown -R 10001:10001 /var/lib/opsswarm

# Copy and install built wheel and runtime dependencies from builder
COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

ENV APP_ENV=production
ENV OPSWARM_DATA_DIR=/var/lib/opsswarm
ENV PORT=8088

EXPOSE 8088

USER 10001:10001

ENTRYPOINT ["uvicorn", "opsswarm.api:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1"]
