"""Unit tests for the Alembic environment's database URL resolution.

``migrations/env.py`` is the operational entry point for applying the HA
coordination schema.  It is normally exercised through a live database, so
the URL handling is pinned here with tests that need no server at all.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")


def _run_offline_upgrade(url: str) -> subprocess.CompletedProcess[str]:
    """Run ``alembic upgrade head --sql`` with the given URL.

    Offline mode renders the migration as SQL and never opens a connection,
    so this exercises URL resolution without needing a database server.
    """
    env = dict(os.environ)
    env["HA_DATABASE_URL"] = url
    env.pop("HA_TEST_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _load_normalise_url():
    """Load ``_normalise_url`` from ``migrations/env.py``.

    The module executes Alembic-specific code at import time, so the Alembic
    context is stubbed out.  Only the pure URL helper is under test.
    """
    import importlib.util
    from unittest import mock

    env_path = os.path.join(REPO_ROOT, "migrations", "env.py")
    spec = importlib.util.spec_from_file_location("ha_migrations_env", env_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with mock.patch("alembic.context") as stub_context:
        stub_context.config.config_file_name = None
        stub_context.is_offline_mode.return_value = True
        spec.loader.exec_module(module)

    return module._normalise_url


def test_documented_bare_postgresql_url_is_accepted() -> None:
    """The documented ``postgresql://`` form must drive the migration.

    SQLAlchemy 2.x resolves a bare ``postgresql://`` URL to the psycopg
    *version 3* driver.  This project depends on ``psycopg2-binary`` only, so
    the documented invocation used to fail with ``ModuleNotFoundError: No
    module named 'psycopg'`` before any migration ran.  Naming the installed
    driver keeps the documented form working.
    """
    result = _run_offline_upgrade("postgresql://user:secret@localhost:5432/opsswarm_ha")
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE runs" in result.stdout


def test_explicitly_driven_url_is_left_untouched() -> None:
    """A URL that already names a driver is used as-is.

    An operator may deliberately select a different driver, so an explicit
    ``postgresql+psycopg://`` URL must not be rewritten.
    """
    result = _run_offline_upgrade(
        "postgresql+psycopg://user:secret@localhost:5432/opsswarm_ha"
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE runs" in result.stdout


def test_missing_url_is_reported_clearly() -> None:
    """Without any URL the environment must explain what to set."""
    env = dict(os.environ)
    env.pop("HA_DATABASE_URL", None)
    env.pop("HA_TEST_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "HA_DATABASE_URL" in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@localhost:5432/opsswarm_ha",
        "postgresql+psycopg2://user:secret@localhost:5432/opsswarm_ha",
    ],
)
def test_normalise_url_is_idempotent_and_never_downgrades_a_driver(url: str) -> None:
    """Normalising an already-normalised URL changes nothing.

    ``migrations/env.py`` runs Alembic-specific code at import time, so the
    module is loaded with a stubbed Alembic context.  Only the pure URL
    helper is under test here.
    """
    normalise = _load_normalise_url()
    once = normalise(url)
    assert normalise(once) == once, "normalisation must be idempotent"
    assert once.startswith("postgresql+psycopg2://")
    assert not once.startswith("postgresql+psycopg2+")
