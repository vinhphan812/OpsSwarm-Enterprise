"""
Root pytest configuration for the `tests/` directory tree.

Sets up sys.path so that `from retailtwin_api import ...` works regardless
of whether pytest is invoked from `apps/api/` or the repository root.

This file is intentionally empty except for the path-setup comment; the real
shared fixtures live in `tests/e2e/conftest.py`.
"""

import sys
from pathlib import Path

# Allow `from retailtwin_api` to resolve from `apps/api/retailtwin_api/`
_api_path = Path(__file__).parent.parent / "apps" / "api"
if _api_path.exists() and str(_api_path) not in sys.path:
    sys.path.insert(0, str(_api_path))
