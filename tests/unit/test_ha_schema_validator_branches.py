"""Regression tests for the deviation branches of the HA schema validator.

The validator is the machine-checkable half of ADR-031's PostgreSQL schema
contract: it compares a live database against
:data:`opsswarm.ha_schema.HA_SCHEMA` and reports every difference.  A
deviation that the validator silently swallows is as dangerous as a wrong
contract, because the failure mode is a schema that drifted while every
green test kept passing.

Each test below pins one branch the validator can take against a database
that deviates from the contract in exactly one way, so a future change that
drops one of these reports fails here instead of in production.
"""

from __future__ import annotations

import pytest

from opsswarm.ha_schema import (
    HA_SCHEMA_BY_NAME,
    HA_TABLE_NAMES,
    SchemaInspectionError,
    SchemaValidationReport,
    validate_ha_schema,
)


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


def _kinds(report: SchemaValidationReport) -> set[str]:
    return {issue.kind for issue in report.issues}


# --------------------------------------------------------------------------- #
# Report shape
# --------------------------------------------------------------------------- #


def test_a_conforming_database_describes_itself_as_valid() -> None:
    """A clean report reads as a success, not as an empty list of issues.

    Operators see this text in the incident log, so an empty report must not
    look like a failure that happened to find nothing wrong.
    """
    report = validate_ha_schema(_ConformingInspector())

    assert report.ok is True
    description = report.describe()
    assert description.startswith("HA schema valid")
    assert str(len(HA_TABLE_NAMES)) in description


def test_require_accepts_a_conforming_database() -> None:
    """``require()`` must not raise when the schema satisfies the contract."""
    report = validate_ha_schema(_ConformingInspector())

    report.require()


def test_a_table_spec_exposes_its_column_names() -> None:
    """``TableSpec.column_names`` is the ordered column-name tuple."""
    spec = HA_SCHEMA_BY_NAME["runs"]

    assert spec.column_names == tuple(column.name for column in spec.columns)
    assert "run_id" in spec.column_names


# --------------------------------------------------------------------------- #
# Structural deviations
# --------------------------------------------------------------------------- #


def test_validator_reports_a_primary_key_mismatch() -> None:
    """A table keyed on the wrong columns is a deviation.

    The evidence table is keyed on ``id``; a database that keyed it on
    ``run_id`` alone would silently collapse the identities the contract
    depends on.
    """

    class _WrongPrimaryKeyInspector(_ConformingInspector):
        def get_pk_constraint(self, table, schema=None):
            if table == "evidence":
                # The contract keys evidence on (id,); run_id alone would let
                # two evidence rows of one run share an identity.
                return {"name": "pk_evidence", "constrained_columns": ["run_id"]}
            return super().get_pk_constraint(table, schema)

    report = validate_ha_schema(_WrongPrimaryKeyInspector())

    assert report.ok is False
    assert "primary_key" in _kinds(report)


def test_validator_reports_a_missing_primary_key() -> None:
    """A table without any primary key is a deviation too."""

    class _NoPrimaryKeyInspector(_ConformingInspector):
        def get_pk_constraint(self, table, schema=None):
            if table == "runs":
                return {"name": None, "constrained_columns": []}
            return super().get_pk_constraint(table, schema)

    report = validate_ha_schema(_NoPrimaryKeyInspector())

    assert report.ok is False
    assert "primary_key" in _kinds(report)


def test_validator_reports_a_foreign_key_that_does_not_cascade() -> None:
    """A foreign key without ``ON DELETE CASCADE`` is a deviation.

    Every coordination table references ``runs(run_id)`` with
    ``ON DELETE CASCADE``.  Without the cascade, deleting a run would either
    fail outright or leave the coordination rows behind, and the next run
    would inherit a stale lease.
    """

    class _NoCascadeInspector(_ConformingInspector):
        def get_foreign_keys(self, table, schema=None):
            foreign_keys = super().get_foreign_keys(table, schema)
            for fk in foreign_keys:
                fk["options"] = {"ondelete": "NO ACTION"}
            return foreign_keys

    report = validate_ha_schema(_NoCascadeInspector())

    assert report.ok is False
    assert "foreign_key_delete_action" in _kinds(report)


def test_validator_reports_a_missing_unique_constraint() -> None:
    """A missing UNIQUE constraint is a deviation.

    ``evidence`` is unique on ``(run_id, id)``; without it two evidence rows
    could share an identity and a replay would be undetectable.
    """

    class _NoUniqueInspector(_ConformingInspector):
        def get_unique_constraints(self, table, schema=None):
            if table == "evidence":
                return []
            return super().get_unique_constraints(table, schema)

    report = validate_ha_schema(_NoUniqueInspector())

    assert report.ok is False
    assert "missing_unique_constraint" in _kinds(report)


def test_validator_reports_a_missing_index() -> None:
    """A missing index is a deviation.

    The contract names the indexes the coordination queries rely on; a
    database that dropped one would still validate every row but serve the
    lease and evidence lookups from a sequential scan.
    """

    class _NoIndexInspector(_ConformingInspector):
        def get_indexes(self, table, schema=None):
            if table == "runs":
                return []
            return super().get_indexes(table, schema)

    report = validate_ha_schema(_NoIndexInspector())

    assert report.ok is False
    assert "missing_index" in _kinds(report)


def test_validator_reports_a_missing_check_constraint() -> None:
    """A missing named CHECK constraint is a deviation.

    ``run_leases_epoch_positive`` is what stops a lease from ever carrying
    epoch ``0`` or a negative epoch, so a database without it accepts
    values the fencing logic cannot reason about.
    """

    class _NoCheckInspector(_ConformingInspector):
        def get_check_constraints(self, table, schema=None):
            if table == "run_leases":
                return []
            return super().get_check_constraints(table, schema)

    report = validate_ha_schema(_NoCheckInspector())

    assert report.ok is False
    assert "missing_check_constraint" in _kinds(report)


def test_a_check_constraint_without_sql_text_is_not_treated_as_time_dependent() -> None:
    """A check constraint with no readable SQL is not flagged as time dependent.

    Some drivers report a check constraint without its expression.  The
    validator cannot prove such a constraint is wall-clock dependent, so it
    must not invent the accusation; the constraint's *name* is still checked
    against the contract by the missing-check branch.
    """

    class _OpaqueCheckInspector(_ConformingInspector):
        def get_check_constraints(self, table, schema=None):
            if table == "run_leases":
                return [{"name": "run_leases_epoch_positive"}]
            return super().get_check_constraints(table, schema)

    report = validate_ha_schema(_OpaqueCheckInspector())

    assert "time_dependent_check" not in _kinds(report)


# --------------------------------------------------------------------------- #
# Inspection failures
# --------------------------------------------------------------------------- #


def test_validator_raises_when_the_table_list_cannot_be_read() -> None:
    """An unreadable catalogue is an error, not a clean report.

    If the table list cannot be read, the validator has no evidence at all.
    Returning an empty report would let a broken connection look like a
    healthy schema.
    """

    class _BrokenInspector(_ConformingInspector):
        def get_table_names(self, schema=None):
            raise RuntimeError("connection refused")

    with pytest.raises(SchemaInspectionError) as excinfo:
        validate_ha_schema(_BrokenInspector())

    assert "connection refused" in str(excinfo.value)


def test_a_schema_without_any_ha_table_reports_every_table_as_missing() -> None:
    """An empty database is reported as missing every contract table."""
    report = validate_ha_schema(_EmptyInspector())

    missing = [issue for issue in report.issues if issue.kind == "missing_table"]
    assert {issue.table for issue in missing} == set(HA_TABLE_NAMES)


class _EmptyInspector(_ConformingInspector):
    """An inspector that reports an empty database."""

    def get_table_names(self, schema=None):
        return []
