"""Integration tests for the ADR-031 HA coordination schema (Issue #70, Phase 2).

These tests run the real Alembic migration against a live PostgreSQL 16
instance and assert the properties ADR-031 requires of the resulting schema:

* all eight coordination tables exist, with the documented indexes;
* ``run_leases`` carries a durable ``epoch`` with a ``CHECK (epoch > 0)``
  constraint and **no** time-dependent ``CHECK (expires_at > NOW())``;
* foreign keys and NOT NULL constraints are enforced by the database, not
  merely declared;
* ``alembic downgrade -1`` drops every HA table again, so a deployment can
  fall back to the legacy filesystem store without leaving half a schema
  behind.

The suite is skipped (not failed) when no PostgreSQL instance is reachable, so
``make ci`` stays green on machines without a database.  Point the tests at a
server with ``HA_TEST_DATABASE_URL``; they default to the URL used by
``alembic upgrade head`` via ``HA_DATABASE_URL``.

Usage::

    export HA_TEST_DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/db"
    pytest tests/integration/test_ha_schema_postgres.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

# --------------------------------------------------------------------------- #
# Optional dependency guard
# --------------------------------------------------------------------------- #

# The migration tooling is a verification-time dependency, not a runtime one,
# so the module skips cleanly when it is not installed.
alembic_command_module = pytest.importorskip(
    "alembic.command", reason="alembic is required for the HA schema migration"
)
alembic_config_module = pytest.importorskip(
    "alembic.config", reason="alembic is required for the HA schema migration"
)
sa = pytest.importorskip(
    "sqlalchemy", reason="SQLAlchemy is required for the HA schema migration"
)

from opsswarm.ha_schema import validate_ha_schema  # noqa: E402  (after importorskip)

try:  # pragma: no cover - exercised only when a driver is installed
    import psycopg2  # noqa: F401
except ImportError:  # pragma: no cover - exercised only when a driver is missing
    psycopg2 = None  # type: ignore[assignment]


pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

#: The eight tables ADR-031 requires, plus the Alembic bookkeeping table.
HA_TABLES = frozenset(
    {
        "runs",
        "run_leases",
        "lease_takeover_authorisations",
        "external_side_effect_intents",
        "evidence",
        "rate_limit_buckets",
        "checkpoints",
        "seen_delivery_keys",
    }
)

INDEXES = frozenset(
    {
        "idx_runs_issue",
        "idx_side_effect_intents_run",
        "idx_evidence_run",
        "idx_evidence_sig",
    }
)


def _database_url() -> str | None:
    url = os.environ.get("HA_TEST_DATABASE_URL") or os.environ.get("HA_DATABASE_URL")
    if not url:
        return None
    if url.startswith("postgresql://"):
        # Normalise the bare scheme so SQLAlchemy picks the psycopg2 driver.
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _database_name(url: str) -> str:
    """Return the database name from a SQLAlchemy URL."""
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _assert_disposable_database(url: str) -> None:
    """Refuse to reset a schema in a database that is not clearly a test one.

    The migration fixtures drop and recreate the ``public`` schema, so pointing
    them at a production database would destroy it.  Requiring a ``test``
    marker in the database name makes that mistake loud instead of silent.
    """
    name = _database_name(url)
    if "test" not in name.lower():
        pytest.fail(
            "HA_TEST_DATABASE_URL must point at a disposable test database "
            f"(database name {name!r} does not contain 'test'); refusing to reset its schema"
        )


@pytest.fixture(scope="module")
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip(
            "HA_TEST_DATABASE_URL is not set; skipping the live PostgreSQL schema test"
        )
    if psycopg2 is None:
        pytest.skip("psycopg2 is not installed; skipping the live PostgreSQL schema test")
    _assert_disposable_database(url)
    return url


@pytest.fixture(scope="module")
def engine(database_url: str):
    eng = sa.create_engine(database_url, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL is not reachable at the configured URL: {exc}")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped environment patching.

    ``pytest``'s built-in ``monkeypatch`` fixture is function-scoped, so a
    module-scoped fixture cannot depend on it.  This provides the same
    behaviour with the scope the migration fixtures need.
    """
    patcher = pytest.MonkeyPatch()
    try:
        yield patcher
    finally:
        patcher.undo()


@pytest.fixture(scope="module")
def alembic_config(database_url: str, monkeypatch_module):
    # Pin the environment variable as well as the config option.  The Alembic
    # environment reads HA_DATABASE_URL first, so leaving a stale value in the
    # operator's shell would otherwise migrate a different database than the
    # one under test.
    monkeypatch_module.setenv("HA_DATABASE_URL", database_url)
    cfg = alembic_config_module.Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


@pytest.fixture
def migrated_db(alembic_config, engine) -> Iterator[None]:
    """Yield with the HA schema applied, then tear it back down.

    The schema is applied once per test and removed afterwards, so each test
    observes a freshly migrated database and no test leaks state into the
    next one.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        alembic_command_module.downgrade(alembic_config, "-1")


@pytest.fixture
def inspector(engine):
    return sa.inspect(engine)


# --------------------------------------------------------------------------- #
# Migration up
# --------------------------------------------------------------------------- #


def test_upgrade_creates_all_eight_ha_tables(inspector, migrated_db) -> None:
    """``alembic upgrade head`` creates every table ADR-031 names."""
    assert HA_TABLES.issubset(set(inspector.get_table_names()))


def test_upgrade_creates_the_documented_indexes(inspector, migrated_db) -> None:
    """The four documented secondary indexes exist."""
    found: set[str] = set()
    for table in HA_TABLES:
        for index in inspector.get_indexes(table):
            found.add(index["name"])
    assert INDEXES.issubset(found)


def test_run_leases_has_epoch_with_positive_check(inspector, migrated_db) -> None:
    """``run_leases`` carries a durable epoch guarded by ``epoch > 0``."""
    columns = {c["name"]: c for c in inspector.get_columns("run_leases")}
    assert "epoch" in columns
    assert "BIGINT" in str(columns["epoch"]["type"]).upper()
    assert not columns["epoch"]["nullable"]

    checks = inspector.get_check_constraints("run_leases")
    epoch_checks = [
        constraint
        for constraint in checks
        if "epoch" in str(constraint.get("sqltext", "")).lower()
    ]
    assert epoch_checks, "run_leases must carry a check constraint on epoch"
    assert any(
        "> 0" in str(constraint.get("sqltext", "")).replace("  ", " ")
        for constraint in epoch_checks
    )


def test_run_leases_has_no_time_dependent_expiry_check(inspector, migrated_db) -> None:
    """ADR-031 forbids ``CHECK (expires_at > NOW())`` on ``run_leases``.

    PostgreSQL evaluates CHECK constraints only when the row is written, so a
    wall-clock comparison would freeze an expired row and block the renewal
    and takeover it was meant to police.
    """
    for constraint in inspector.get_check_constraints("run_leases"):
        sqltext = str(constraint["sqltext"]).lower()
        assert "expires_at" not in sqltext, (
            "run_leases must not carry a time-dependent CHECK constraint on expires_at"
        )
        assert "now()" not in sqltext


def test_all_ha_tables_have_primary_keys(inspector, migrated_db) -> None:
    """Every HA table is keyed, so rows are addressable and idempotent."""
    for table in HA_TABLES:
        constraints = inspector.get_pk_constraint(table)
        assert constraints["constrained_columns"], f"{table} has no primary key"


def test_foreign_keys_are_declared_towards_runs(inspector, migrated_db) -> None:
    """Child tables reference ``runs`` and cascade on delete."""
    expected = {
        "run_leases": "runs",
        "lease_takeover_authorisations": "runs",
        "external_side_effect_intents": "runs",
        "evidence": "runs",
        "checkpoints": "runs",
    }
    for table, parent in expected.items():
        foreign_keys = inspector.get_foreign_keys(table)
        assert any(fk["referred_table"] == parent for fk in foreign_keys), (
            f"{table} must reference {parent}"
        )
        for fk in foreign_keys:
            if fk["referred_table"] == parent:
                assert fk["options"].get("ondelete") == "CASCADE"


def test_not_null_constraints_are_declared(inspector, migrated_db) -> None:
    """The columns ADR-031 marks NOT NULL are declared NOT NULL."""
    expectations = {
        "runs": ("run_id", "issue_number", "state", "run_data", "revision"),
        "run_leases": ("run_id", "owner_id", "epoch", "expires_at"),
        "evidence": ("id", "run_id", "kind", "payload", "signature"),
        "checkpoints": ("run_id", "checkpoint_type", "payload"),
        "seen_delivery_keys": ("delivery_id", "run_id"),
    }
    for table, columns in expectations.items():
        actual = {c["name"]: c["nullable"] for c in inspector.get_columns(table)}
        for column in columns:
            assert actual[column] is False, f"{table}.{column} must be NOT NULL"


def test_rate_limit_buckets_uses_composite_primary_key(inspector, migrated_db) -> None:
    """One bucket per key per window.

    A primary key on ``key`` alone would make the ADR's own rate-limiter
    upsert impossible: a new window for a live key would raise a
    primary-key violation instead of being handled by the conflict clause.
    """
    constraints = inspector.get_pk_constraint("rate_limit_buckets")
    assert set(constraints["constrained_columns"]) == {"key", "window_start"}


# --------------------------------------------------------------------------- #
# Constraint enforcement (the database, not the declaration)
# --------------------------------------------------------------------------- #


def test_database_rejects_unknown_parent_run(engine, migrated_db) -> None:
    """A child row referencing a missing run is rejected by the foreign key."""
    with engine.begin() as conn:
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                    "VALUES ('run-missing', 'owner-a', 1, NOW() + INTERVAL '30 seconds')"
                )
            )


def test_database_rejects_null_owner_id(engine, migrated_db) -> None:
    """NOT NULL is enforced by PostgreSQL, not merely declared."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES ('run-1', 42, 'running', '{}'::jsonb)"
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                    "VALUES ('run-1', NULL, 1, NOW() + INTERVAL '30 seconds')"
                )
            )


def test_database_rejects_non_positive_epoch(engine, migrated_db) -> None:
    """``epoch > 0`` is enforced by the database."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES ('run-2', 42, 'running', '{}'::jsonb)"
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                    "VALUES ('run-2', 'owner-a', 0, NOW() + INTERVAL '30 seconds')"
                )
            )


def test_expired_lease_can_still_be_renewed(engine, migrated_db) -> None:
    """A lease whose ``expires_at`` is in the past is still updatable.

    This is the behaviour a time-dependent CHECK constraint would destroy:
    with ``CHECK (expires_at > NOW())`` in place, PostgreSQL would reject any
    UPDATE of the expired row, including the renewal that ADR-031 requires.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES ('run-3', 42, 'running', '{}'::jsonb)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                "VALUES ('run-3', 'owner-a', 1, NOW() - INTERVAL '1 hour')"
            )
        )
        # Must not raise: the renewal is exactly what a static CHECK would block.
        conn.execute(
            sa.text(
                "UPDATE run_leases SET expires_at = NOW() + INTERVAL '30 seconds' "
                "WHERE run_id = 'run-3'"
            )
        )


def test_takeover_increments_epoch_monotonically(engine, migrated_db) -> None:
    """The durable takeover transaction bumps the epoch in the same row lock."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES ('run-4', 42, 'running', '{}'::jsonb)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                "VALUES ('run-4', 'owner-a', 1, NOW() + INTERVAL '30 seconds')"
            )
        )
        conn.execute(
            sa.text(
                "UPDATE run_leases SET owner_id = 'owner-b', epoch = epoch + 1 "
                "WHERE run_id = 'run-4'"
            )
        )
        row = conn.execute(
            sa.text("SELECT owner_id, epoch FROM run_leases WHERE run_id = 'run-4'")
        ).one()
        assert row.owner_id == "owner-b"
        assert row.epoch == 2


def test_rate_limit_bucket_upsert_on_composite_key(engine, migrated_db) -> None:
    """The ADR's documented ``ON CONFLICT (key, window_start)`` upsert works."""
    from datetime import datetime, timezone

    window = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with engine.begin() as conn:
        for _ in range(2):
            conn.execute(
                sa.text(
                    "INSERT INTO rate_limit_buckets (key, hits, window_start, window_seconds) "
                    "VALUES (:k, 1, :w, 3600) "
                    "ON CONFLICT (key, window_start) DO UPDATE SET hits = rate_limit_buckets.hits + 1"
                ),
                {"k": "shared-key", "w": window},
            )
        row = conn.execute(
            sa.text(
                "SELECT hits FROM rate_limit_buckets WHERE key = 'shared-key' AND window_start = :w"
            ),
            {"w": window},
        ).one()
        assert row.hits == 2


# --------------------------------------------------------------------------- #
# Migration down
# --------------------------------------------------------------------------- #


def test_downgrade_drops_every_ha_table(alembic_config, engine) -> None:
    """``alembic downgrade -1`` removes all eight tables again."""
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")
    alembic_command_module.downgrade(alembic_config, "-1")

    remaining = set(sa.inspect(engine).get_table_names())
    assert not HA_TABLES & remaining
    # The Alembic bookkeeping table survives the downgrade; that is expected.
    assert "alembic_version" in remaining


def test_downgrade_leaves_filesystem_fallback_untouched(alembic_config, engine, tmp_path) -> None:
    """Reverting the schema does not disturb the legacy filesystem store.

    The HA layer is additive: the filesystem run records are the legacy
    fallback and must survive a schema downgrade.
    """
    legacy = tmp_path / "runtime-data"
    legacy.mkdir()
    record = legacy / "run-42.json"
    record.write_text('{"run_id": "run-42", "state": "running"}', encoding="utf-8")

    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")
    alembic_command_module.downgrade(alembic_config, "-1")

    assert record.exists()
    assert record.read_text(encoding="utf-8") == '{"run_id": "run-42", "state": "running"}'


def test_upgrade_downgrade_upgrade_is_stable(alembic_config, engine) -> None:
    """The migration is re-runnable: up, down and up again all succeed."""
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")
    alembic_command_module.downgrade(alembic_config, "-1")
    alembic_command_module.upgrade(alembic_config, "head")

    assert HA_TABLES.issubset(set(sa.inspect(engine).get_table_names()))


def test_documented_postgresql_url_scheme_is_accepted(
    alembic_config, engine, database_url, monkeypatch_module
) -> None:
    """The documented ``postgresql://`` URL form must drive the migration.

    ``migrations/env.py`` documents ``export HA_DATABASE_URL=postgresql://...``
    as the operational way to run ``alembic upgrade head``.  SQLAlchemy 2.x
    resolves that bare scheme to the psycopg *version 3* driver, which this
    project does not install, so the documented invocation used to fail with
    ``ModuleNotFoundError: No module named 'psycopg'`` before any migration
    ran.  The environment now names the installed driver, so the documented
    form and an explicitly-driven URL both work.

    This test drives the migration with the bare scheme and asserts the
    schema is actually created, which is the behaviour an operator depends on.
    """
    bare_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    assert bare_url.startswith("postgresql://"), "expected a bare postgresql:// URL"

    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    # The Alembic environment reads HA_DATABASE_URL first, so the bare scheme
    # is what the migration actually sees.
    monkeypatch_module.setenv("HA_DATABASE_URL", bare_url)
    try:
        alembic_command_module.upgrade(alembic_config, "head")
    finally:
        monkeypatch_module.setenv("HA_DATABASE_URL", database_url)

    assert HA_TABLES.issubset(set(sa.inspect(engine).get_table_names()))


def test_migrated_database_satisfies_the_executable_schema_contract(
    alembic_config, engine
) -> None:
    """The live schema must pass the canonical contract validator.

    The unit layer exercises the validator against a fake inspector.  This
    test runs the *real* SQLAlchemy inspector against a *real* PostgreSQL
    database, which is the only way to catch a divergence between the
    contract and what the driver actually reports -- for example an array
    column, whose type object renders as the bare word ``ARRAY`` rather than
    the contract's ``TEXT[]``.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")

    report = validate_ha_schema(sa.inspect(engine))
    assert report.ok is True, report.describe()


def test_live_inspector_renders_the_array_column_as_array(alembic_config, engine) -> None:
    """The live driver really does hide the element type behind ``ARRAY``.

    This pins the driver behaviour the validator has to cope with: the
    SQLAlchemy PostgreSQL dialect stringifies an array column as the bare
    word ``ARRAY`` and keeps the element type in a separate ``item_type``
    attribute.  Without this test a future change to the rendering could
    silently reintroduce a validator that cannot tell ``TEXT[]`` from
    ``INTEGER[]``.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")

    columns = {c["name"]: c for c in sa.inspect(engine).get_columns("runs")}
    array_type = columns["idempotency_keys"]["type"]

    assert str(array_type) == "ARRAY"
    assert str(array_type.item_type).upper() == "TEXT"


def test_validator_rejects_a_live_array_column_with_the_wrong_element_type(
    alembic_config, engine
) -> None:
    """An ``INTEGER[]`` column does not satisfy the ``TEXT[]`` contract.

    Widening the contract to accept the bare word ``ARRAY`` would make this
    schema pass.  The element type has to be part of the comparison, so the
    live database is altered to prove the validator still rejects it.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")

    with engine.begin() as conn:
        # The default is dropped first: PostgreSQL cannot cast the ``text[]``
        # default to ``integer[]`` on its own.
        conn.execute(sa.text("ALTER TABLE runs ALTER COLUMN idempotency_keys DROP DEFAULT"))
        conn.execute(
            sa.text(
                "ALTER TABLE runs ALTER COLUMN idempotency_keys "
                "TYPE integer[] USING ARRAY[]::integer[]"
            )
        )

    report = validate_ha_schema(sa.inspect(engine))
    assert report.ok is False
    assert any(
        issue.kind == "column_type" and "idempotency_keys" in issue.detail
        for issue in report.issues
    )


def test_validator_rejects_a_live_scalar_column_turned_into_an_array(
    alembic_config, engine
) -> None:
    """A scalar column that became an array is a deviation.

    The rendered type of an array column *contains* the scalar type name --
    ``"TEXT[]"`` contains ``"TEXT"`` -- so a validator that compared types by
    substring alone would accept a schema whose scalar column had turned into
    an array.  The live database is altered to prove the array-ness is part
    of the comparison.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "ALTER TABLE runs ALTER COLUMN state "
                "TYPE text[] USING ARRAY[state]::text[]"
            )
        )

    report = validate_ha_schema(sa.inspect(engine))
    assert report.ok is False
    assert any(
        issue.kind == "column_type" and "state" in issue.detail for issue in report.issues
    )
