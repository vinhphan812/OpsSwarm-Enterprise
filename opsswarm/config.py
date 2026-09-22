from __future__ import annotations
import os, re
from pathlib import Path
from typing import Any
import yaml

_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _PATTERN.sub(lambda m: os.getenv(m.group(1), m.group(0)), value)
    if isinstance(value, list): return [_expand(v) for v in value]
    if isinstance(value, dict): return {k: _expand(v) for k, v in value.items()}
    return value

def load_config(path: str | None = None) -> dict[str, Any]:
    path = path or os.getenv("OPSWARM_CONFIG", "config/production.yaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return _expand(data)
