from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _PATTERN.sub(lambda m: os.getenv(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: str | None = None) -> dict[str, Any]:
    path = path or os.getenv("OPSWARM_CONFIG", "config/production.yaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return _expand(data)


# ----------------------------------------------------------------------
# Issue #26 — Execution budget defaults
# ----------------------------------------------------------------------

# Reasonable defaults for a single incident run.
# These can be overridden per-deployment in production.yaml.
DEFAULT_BUDGET = {
    "max_tasks_per_run": 50,
    "max_openclaw_calls": 200,
    "max_wall_clock_seconds": 3600,   # 1 hour
    "max_corrective_actions": 10,
    "max_dependency_depth": 20,
}

# Concurrency defaults
DEFAULT_CONCURRENCY = {
    "max_parallel_specialists": 4,
}


def get_budget(cfg: dict) -> dict:
    """Return the budget section from config, merged with defaults."""
    return {**DEFAULT_BUDGET, **cfg.get("budget", {})}


def get_concurrency(cfg: dict) -> dict:
    """Return the concurrency section from config, merged with defaults."""
    return {**DEFAULT_CONCURRENCY, **cfg.get("concurrency", {})}
