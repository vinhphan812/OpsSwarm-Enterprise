"""Regression coverage for demo-runtime namespace isolation."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "retailtwin_api"
DEMO_RUNTIME = API_ROOT / "demo_runtime"
DELETED_CANONICAL_PATHS = (
    API_ROOT / "demo.py",
    API_ROOT / "agents" / "executor",
    API_ROOT / "agents" / "verifier",
    API_ROOT / "services" / "twin",
    API_ROOT / "services" / "simulation",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "retailtwin_api.demo_runtime",
    "retailtwin_api.demo",
    "retailtwin_api.agents.executor",
    "retailtwin_api.agents.verifier",
    "retailtwin_api.services.twin",
    "retailtwin_api.services.simulation",
)


def _non_demo_modules() -> list[Path]:
    return sorted(
        path
        for path in API_ROOT.rglob("*.py")
        if DEMO_RUNTIME not in path.parents and path != DEMO_RUNTIME
    )


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_canonical_demo_namespaces_are_deleted() -> None:
    assert all(not path.exists() for path in DELETED_CANONICAL_PATHS)


@pytest.mark.parametrize("path", _non_demo_modules())
def test_non_demo_modules_do_not_import_demo_runtime_or_canonical_aliases(path: Path) -> None:
    violations = [
        imported
        for imported in _imports(path)
        if imported.startswith(FORBIDDEN_IMPORT_PREFIXES)
    ]
    assert not violations, f"{path.relative_to(API_ROOT)} imports isolated demo code: {violations}"


def test_main_and_routes_are_non_demo_modules() -> None:
    assert {API_ROOT / "main.py", API_ROOT / "routes.py"}.issubset(_non_demo_modules())
