"""Alembic environment for the OpsSwarm HA coordination schema (ADR-031).

The database URL is never hardcoded.  It is read from the ``HA_DATABASE_URL``
environment variable, so the same migration scripts can be applied to a local
container, a staging cluster, or a managed writer endpoint without editing
tracked files.

Usage::

    export HA_DATABASE_URL="postgresql://user:secret@host:5432/opsswarm_ha"
    alembic upgrade head
    alembic downgrade -1
    alembic current
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# The Alembic Config object provides access to the values within the .ini file.
config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers must stay False.  Alembic's own env.py template
    # omits the argument, which makes logging.config disable every logger that
    # already exists.  When the migration is driven from inside a test session
    # that silently disables the application's loggers, and any later test that
    # asserts on captured log records sees an empty capture.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The HA coordination schema is defined by an explicit, hand-written migration
# (migrations/versions/001_initial_ha_schema.py).  There is no ORM model
# metadata to autogenerate against, so target_metadata stays None and
# `alembic revision --autogenerate` is intentionally not part of the workflow.
target_metadata = None

_URL_ENV_VAR = "HA_DATABASE_URL"


def get_url() -> str:
    """Return the database URL to migrate.

    Precedence:

    1. The ``HA_DATABASE_URL`` environment variable.  This is the operational
       path: an operator exports the URL for the target writer and runs
       ``alembic upgrade head``.
    2. The ``sqlalchemy.url`` option of the Alembic config, when a caller has
       set it explicitly (for example a test harness driving the migration
       programmatically).

    Raises:
        EnvironmentError: If neither source supplies a URL.
    """
    url = os.getenv(_URL_ENV_VAR)
    if not url:
        url = config.get_main_option("sqlalchemy.url", None)
    if not url:
        raise EnvironmentError(
            f"{_URL_ENV_VAR} environment variable is not set. "
            "Set it to the PostgreSQL connection string for the HA "
            "coordination database, for example:\n"
            "  export HA_DATABASE_URL=postgresql://user:***@localhost:5432/opsswarm_ha"
        )
    return _normalise_url(url)


def _normalise_url(url: str) -> str:
    """Return the URL with an explicit driver that this project installs.

    SQLAlchemy 2.x resolves a bare ``postgresql://`` URL to the psycopg
    *version 3* driver.  This project depends on ``psycopg2-binary`` only, so
    the documented ``postgresql://user:***@host:5432/db`` invocation fails
    with ``ModuleNotFoundError: No module named 'psycopg'`` before any
    migration runs.  Naming the installed driver keeps the documented form
    working and keeps the driver choice explicit.

    A URL that already names a driver is left untouched, so an operator can
    still select a different driver deliberately.
    """
    if not url.startswith("postgresql://"):
        return url
    return "postgresql+psycopg2://" + url[len("postgresql://") :]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL to the script output."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
