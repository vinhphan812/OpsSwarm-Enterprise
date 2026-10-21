"""
Alembic environment configuration for OpsSwarm HA migrations.

Loads database URL from the HA_DATABASE_URL environment variable so that
migrations can be run without hardcoding credentials.

Usage:
    alembic upgrade head
    alembic downgrade -1
    alembic history --verbose
    alembic current
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import models so that Alembic can auto-generate migrations from SQLAlchemy models.
# We import the base and metadata directly rather than individual models to avoid
# circular import issues at the alembic level.
from opsswarm.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def get_url() -> str:
    """Return the database URL from the HA_DATABASE_URL environment variable.

    Raises:
        EnvironmentError: If HA_DATABASE_URL is not set.
    """
    url = os.getenv("HA_DATABASE_URL")
    if not url:
        raise EnvironmentError(
            "HA_DATABASE_URL environment variable is not set. "
            "Set it to your PostgreSQL connection string, e.g.:\n"
            "  export HA_DATABASE_URL=postgresql://user:pass@localhost:5432/opsswarm_ha"
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
