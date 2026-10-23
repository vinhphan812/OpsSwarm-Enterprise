"""Unit tests for the ADR-031 HA schema contract and validator (Issue #70, Phase 2).

These tests do not require a database: they exercise the canonical contract in
:mod:`opsswarm.ha_schema` against a fake inspector, and they check that the
migration module and the contract stay in agreement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opsswarm.ha_schema import (
    HA_SCHEMA,
    HA_SCHEMA_BY_NAME,
    HA_TABLE_NAMES,
    SchemaValidationError,
    SchemaValidationReport,
    TableSpec,
    validate_ha_schema,
)
from opsswarm.ha_schema import validate_ha_schema as store_validate_ha_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = REPO_ROOT / "migrations" / "versions" / "001_initial_ha_schema.py"


def _migration_source() -> str:
    """Return the text of the initial HA migration."""
    return MIGRATION_FILE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Contract shape
# --------------------------------------------------------------------------- #


def test_contract_declares_the_eight_ha_tables() -> None:
    """ADR-031 names exactly eight coordination tables."""
    assert set(HA_TABLE_NAMES) == {
        "runs",
        "run_leases",
        "lease_takeover_authorisations",
        "external_side_effect_intents",
        "evidence",
        "rate_limit_buckets",
        "checkpoints",
        "seen_delivery_keys",
    }
    assert len(HA_SCHEMA) == 8


def test_run_leases_contract_uses_epoch_not_fencing_token() -> None:
    """ADR-031 replaced ``fencing_token`` with a durable ``epoch``."""
    leases = HA_SCHEMA_BY_NAME["run_leases"]
    column_names = {column.name for column in leases.columns}
    assert "epoch" in column_names
    assert "fencing_token" not in column_names


def test_run_leases_epoch_is_non_nullable() -> None:
    """The epoch must always be present; a NULL epoch cannot fence anything."""
    leases = HA_SCHEMA_BY_NAME["run_leases"]
    epoch = next(column for column in leases.columns if column.name == "epoch")
    assert epoch.nullable is False


def test_no_table_declares_a_time_dependent_check() -> None:
    """No contract entry may encode a wall-clock comparison in a CHECK.

    PostgreSQL evaluates CHECK constraints on write only, so a constraint such
    as ``expires_at > NOW()`` would freeze an expired row and block renewal
    and takeover.
    """
    for table in HA_SCHEMA:
        for check in table.check_constraints:
            lowered = check.lower()
            assert "now()" not in lowered, f"{table.name} declares a time-dependent check"
            assert "expires_at" not in lowered, f"{table.name} declares a time-dependent check"


def test_every_table_has_a_primary_key() -> None:
    """Every coordination table is keyed."""
    for table in HA_SCHEMA:
        assert table.primary_key, f"{table.name} must declare a primary key"


def test_child_tables_declare_a_foreign_key_to_runs() -> None:
    """Child tables reference ``runs`` and cascade on delete."""
    expected = {
        "run_leases",
        "lease_takeover_authorisations",
        "external_side_effect_intents",
        "evidence",
        "checkpoints",
    }
    for name in expected:
        table = HA_SCHEMA_BY_NAME[name]
        assert table.foreign_keys, f"{name} must declare a foreign key"
        assert any(fk.referred_table == "runs" for fk in table.foreign_keys)
        assert all(fk.ondelete == "CASCADE" for fk in table.foreign_keys)


def test_contract_tables_are_ordered_deterministically() -> None:
    """The contract is a stable, ordered mapping."""
    assert [table.name for table in HA_SCHEMA] == list(HA_TABLE_NAMES)
    assert isinstance(HA_SCHEMA_BY_NAME["runs"], TableSpec)
    assert set(HA_SCHEMA_BY_NAME) == set(HA_TABLE_NAMES)


def test_rate_limit_buckets_uses_a_composite_primary_key() -> None:
    """One bucket per key per window.

    A primary key on ``key`` alone would break the ADR's own rate-limiter
    upsert: a new window for a live key would raise a primary-key violation
    instead of being handled by the conflict clause.
    """
    assert HA_SCHEMA_BY_NAME["rate_limit_buckets"].primary_key == ("key", "window_start")


# --------------------------------------------------------------------------- #
# Validator against a fake inspector
# --------------------------------------------------------------------------- #


class _FakeInspector:
    """Minimal duck-typed inspector that reports a deliberately broken schema.

    It models a database where ``runs`` is missing entirely and
    ``run_leases`` has the wrong column set, so the validator has something
    concrete to report.
    """

    def get_table_names(self, schema=None):
        return ["run_leases"]

    def get_columns(self, table, schema=None):
        if table != "run_leases":
            return []
        return [
            {"name": "run_id", "type": "TEXT", "nullable": False},
            # Deliberately the wrong type: the contract expects TEXT.
            {"name": "owner_id", "type": "INTEGER", "nullable": True},
        ]

    def get_pk_constraint(self, table, schema=None):
        return {"name": "pk_run_leases", "constrained_columns": ["run_id"]}

    def get_foreign_keys(self, table, schema=None):
        return []

    def get_unique_constraints(self, table, schema=None):
        return []

    def get_check_constraints(self, table, schema=None):
        return []

    def get_indexes(self, table, schema=None):
        return []


def test_validator_reports_a_missing_table() -> None:
    """A table present in the contract but absent from the database is reported."""
    report = validate_ha_schema(_FakeInspector())
    assert isinstance(report, SchemaValidationReport)
    assert report.ok is False
    assert any(
        issue.kind == "missing_table" and issue.table == "runs" for issue in report.issues
    )


def test_validator_reports_a_missing_column() -> None:
    """A column absent from the database is reported."""
    report = validate_ha_schema(_FakeInspector())
    assert any(
        issue.kind == "missing_column" and "epoch" in issue.detail for issue in report.issues
    )


def test_validator_reports_a_nullable_column() -> None:
    """A column that should be NOT NULL but is nullable is reported."""
    report = validate_ha_schema(_FakeInspector())
    assert any(
        issue.kind == "column_nullability" and "owner_id" in issue.detail
        for issue in report.issues
    )


def test_validator_reports_a_missing_foreign_key() -> None:
    """A missing foreign key towards ``runs`` is reported."""
    report = validate_ha_schema(_FakeInspector())
    assert any(issue.kind == "missing_foreign_key" for issue in report.issues)


def test_validator_reports_a_wrong_column_type() -> None:
    """A column with the wrong database type is reported."""
    report = validate_ha_schema(_FakeInspector())
    assert any(issue.kind == "column_type" for issue in report.issues)


def test_report_describes_itself_for_operators() -> None:
    """The report has a readable summary for operator-facing output."""
    report = validate_ha_schema(_FakeInspector())
    description = report.describe()
    assert description
    assert "[missing_table]" in description


def test_report_require_raises_when_not_compliant() -> None:
    """``require()`` fails closed so callers cannot ignore a broken schema."""
    report = validate_ha_schema(_FakeInspector())
    with pytest.raises(SchemaValidationError) as excinfo:
        report.require()
    assert excinfo.value.report is report


def test_store_reexport_delegates_to_the_contract_validator() -> None:
    """``opsswarm.store.validate_ha_schema`` is the documented entry point."""
    report = store_validate_ha_schema(_FakeInspector())
    assert isinstance(report, SchemaValidationReport)
    assert report.ok is False


class _ConformingInspector:
    """An inspector that reports exactly what the contract describes."""

    def get_table_names(self, schema=None):
        return list(HA_TABLE_NAMES)

    def get_columns(self, table, schema=None):
        spec = HA_SCHEMA_BY_NAME[table]
        return [
            {"name": column.name, "type": column.type_tokens[0], "nullable": column.nullable}
            for column in spec.columns
        ]

    def get_pk_constraint(self, table, schema=None):
        return {
            "name": f"pk_{table}",
            "constrained_columns": list(HA_SCHEMA_BY_NAME[table].primary_key),
        }

    def get_foreign_keys(self, table, schema=None):
        return [
            {
                "constrained_columns": list(fk.columns),
                "referred_table": fk.referred_table,
                "referred_columns": list(fk.referred_columns),
                "options": {"ondelete": fk.ondelete} if fk.ondelete else {},
            }
            for fk in HA_SCHEMA_BY_NAME[table].foreign_keys
        ]

    def get_unique_constraints(self, table, schema=None):
        return [
            {"name": f"uq_{table}_{index}", "column_names": list(columns)}
            for index, columns in enumerate(HA_SCHEMA_BY_NAME[table].unique_constraints)
        ]

    def get_check_constraints(self, table, schema=None):
        return [
            {"name": name, "sqltext": f"CHECK ({name})"}
            for name in HA_SCHEMA_BY_NAME[table].check_constraints
        ]

    def get_indexes(self, table, schema=None):
        return [{"name": name, "column_names": []} for name in HA_SCHEMA_BY_NAME[table].indexes]


def test_validator_accepts_a_conforming_database() -> None:
    """A database matching the contract validates cleanly."""
    report = validate_ha_schema(_ConformingInspector())
    assert report.ok is True, report.describe()
    assert report.issues == ()


def test_validator_flags_a_time_dependent_check_constraint() -> None:
    """A live database carrying ``expires_at > NOW()`` is rejected."""

    class _TimeDependentInspector(_ConformingInspector):
        def get_check_constraints(self, table, schema=None):
            checks = super().get_check_constraints(table, schema)
            if table == "run_leases":
                checks.append(
                    {
                        "name": "run_leases_no_expired_leases",
                        "sqltext": "CHECK (expires_at > NOW())",
                    }
                )
            return checks

    report = validate_ha_schema(_TimeDependentInspector())
    assert report.ok is False
    assert any(issue.kind == "time_dependent_check" for issue in report.issues)


# --------------------------------------------------------------------------- #
# Migration / contract agreement
# --------------------------------------------------------------------------- #


def test_migration_declares_the_epoch_positive_check() -> None:
    """The ``epoch > 0`` constraint is present in the migration."""
    text = _migration_source()
    assert "epoch > 0" in text
    assert "run_leases_epoch_positive" in text


def test_migration_has_no_executable_time_dependent_check() -> None:
    """The migration itself must not introduce a wall-clock CHECK."""
    for line in _migration_source().splitlines():
        stripped = line.strip()
        if stripped.startswith(("sa.CheckConstraint(", "sa.checkconstraint(")):
            assert "now()" not in stripped.lower()
            assert "expires_at" not in stripped.lower()


def test_migration_creates_no_fencing_token_column() -> None:
    """The superseded ``fencing_token`` name must not reappear."""
    assert "fencing_token" not in _migration_source()


@pytest.mark.parametrize("table", sorted(HA_TABLE_NAMES))
def test_migration_creates_every_contract_table(table: str) -> None:
    """Each contract table is created by the migration."""
    assert f'"{table}"' in _migration_source()


def test_migration_drops_every_contract_table_on_downgrade() -> None:
    """Every created table is dropped again by the down migration."""
    downgrade = _migration_source().split("def downgrade()", 1)[1]
    for table in HA_TABLE_NAMES:
        assert f'op.drop_table("{table}")' in downgrade


def test_migration_defines_the_documented_revision_identifiers() -> None:
    """The revision is the initial one and has no parent."""
    source = _migration_source()
    assert 'revision = "001_initial_ha_schema"' in source
    assert "down_revision = None" in source
