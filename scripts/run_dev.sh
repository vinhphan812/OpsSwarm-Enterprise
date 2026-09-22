#!/usr/bin/env bash
set -euo pipefail
export OPSWARM_CONFIG="${OPSWARM_CONFIG:-config/production.yaml}"
exec uvicorn opsswarm.api:app --host 0.0.0.0 --port "${PORT:-8088}" --reload
