"""Canonical HA coordination schema contract (ADR-031).

This module is the single declarative source of truth for the PostgreSQL
coordination schema that ``migrations/versions/001_initial_ha_schema.py``
creates.  It intentionally depends on the standard library only, so it can be
imported by the runtime package without pulling in a database driver or an
ORM.

Why this exists
---------------
ADR-031 splits the HA work into phases, and each phase is verified against a
real PostgreSQL instance.  Without a machine-checkable description of the
schema, the DDL in the Alembic migration and the expectations of the later
phases (lease management, CAS enforcement, readiness) can silently drift apart.
:class:`HA_SCHEMA` is that description, and :func:`validate_ha_schema` checks a
live database against it.

The validator deliberately consumes a *duck-typed* inspector rather than
importing SQLAlchemy: the runtime package pins its dependencies, so the
coordination contract must stay importable without a driver installed.  A
SQLAlchemy ``Inspector`` satisfies the protocol, and the integration test
passes one directly.

Contract highlights enforced here
---------------------------------
* ``run_leases`` carries a durable, strictly increasing ``epoch`` with a
  ``epoch > 0`` check constraint.
* No table carries a time-dependent ``CHECK (expires_at > NOW())`` constraint.
  PostgreSQL evaluates a check constraint only when the row is written, so such
  a constraint silently freezes the row once the lease expires and blocks the
  very renewal or takeover it was meant to police.  Lease expiry is therefore
  evaluated dynamically, inside the acquisition transaction, using PostgreSQL
  server time.  :func:`validate_ha_schema` actively fails on such a constraint.
* Every coordination table that references a run references ``runs(run_id)`` with
  ``ON DELETE CASCADE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

__all__ = [
    "ColumnSpec",
    "ForeignKeySpec",
    "HA_SCHEMA",
    "HA_SCHEMA_BY_NAME",
    "HA_TABLE_NAMES",
    "SchemaInspectionError",
    "SchemaInspector",
    "SchemaValidationError",
    "SchemaValidationIssue",
    "SchemaValidationReport",
    "TableSpec",
    "validate_ha_schema",
]


class SchemaInspectionError(RuntimeError):
    """Raised when the live schema cannot be inspected at all."""


class SchemaValidationError(RuntimeError):
    """Raised when the live schema does not satisfy the HA contract."""

    def __init__(self, report: "SchemaValidationReport") -> None:
        self.report = report
        detail = "; ".join(issue.describe() for issue in report.issues)
        super().__init__(f"HA schema validation failed ({len(report.issues)} issue(s)): {detail}")


@dataclass(frozen=True)
class ColumnSpec:
    """Expected column definition.

    ``type_tokens`` are uppercase substrings that must all appear in the
    rendered database type.  Substring matching keeps the contract independent
    of driver-specific type objects (``TEXT[]`` vs ``ARRAY`` vs
    ``VARCHAR(64)``) while still catching a genuinely wrong column type.
    """

    name: str
    type_tokens: tuple[str, ...]
    nullable: bool = False

    def type_matches(self, rendered_type: str) -> bool:
        rendered = rendered_type.upper()
        return all(token in rendered for token in self.type_tokens)


@dataclass(frozen=True)
class ForeignKeySpec:
    """Expected foreign key relationship."""

    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    ondelete: str | None = None


@dataclass(frozen=True)
class TableSpec:
    """Expected definition of a single coordination table."""

    name: str
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKeySpec, ...] = ()
    unique_constraints: tuple[tuple[str, ...], ...] = ()
    check_constraints: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


class SchemaInspector(Protocol):
    """The subset of the SQLAlchemy inspector API the validator relies on.

    Any object exposing these methods works, which keeps the runtime package
    free of an ORM dependency and makes the validator trivially unit-testable.
    """

    def get_table_names(self) -> Sequence[str]:
        """Return every table name visible to the inspector."""

    def get_columns(self, table_name: str, schema: str | None = None) -> Sequence[Mapping[str, Any]]:
        """Return the column mappings for a table."""

    def get_pk_constraint(
        self, table_name: str, schema: str | None = None
    ) -> Mapping[str, Any]:
        """Return the primary key constraint mapping for a table."""

    def get_foreign_keys(
        self, table_name: str, schema: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        """Return the foreign key mappings for a table."""

    def get_unique_constraints(
        self, table_name: str, schema: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        """Return the unique constraint mappings for a table."""

    def get_check_constraints(
        self, table_name: str, schema: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        """Return the check constraint mappings for a table."""

    def get_indexes(self, table_name: str, schema: str | None = None) -> Sequence[Mapping[str, Any]]:
        """Return the index mappings for a table."""


@dataclass(frozen=True)
class SchemaValidationIssue:
    """A single deviation between the live schema and the contract."""

    kind: str
    table: str | None
    detail: str

    def describe(self) -> str:
        location = self.table or "<schema>"
        return f"[{self.kind}] {location}: {self.detail}"


@dataclass(frozen=True)
class SchemaValidationReport:
    """Outcome of validating a live schema against :data:`HA_SCHEMA`."""

    issues: tuple[SchemaValidationIssue, ...] = field(default_factory=tuple)
    tables_checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Return True when the live schema satisfies the contract."""
        return not self.issues

    def require(self) -> None:
        """Raise :class:`SchemaValidationError` when the schema is not compliant."""
        if not self.ok:
            raise SchemaValidationError(self)

    def describe(self) -> str:
        """Return a human readable summary of the report."""
        if self.ok:
            return f"HA schema valid ({len(self.tables_checked)} table(s) checked)"
        return "\n".join(issue.describe() for issue in self.issues)


# --------------------------------------------------------------------------
# The contract itself.
#
# Names, types and constraints mirror the "PostgreSQL Schema" section of
# ADR-031 (docs/adr/ADR-031_HA_COORDINATION.md).
# --------------------------------------------------------------------------

_HA_SCHEMA: tuple[TableSpec, ...] = (
    TableSpec(
        name="runs",
        columns=(
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("issue_number", ("INTEGER",)),
            ColumnSpec("state", ("TEXT",)),
            ColumnSpec("run_data", ("JSONB",)),
            ColumnSpec("revision", ("INTEGER",)),
            ColumnSpec("idempotency_keys", ("TEXT[]",)),
            ColumnSpec("command_outcomes", ("JSONB",)),
            ColumnSpec("created_at", ("TIMESTAMP",)),
            ColumnSpec("updated_at", ("TIMESTAMP",)),
        ),
        primary_key=("run_id",),
        indexes=("idx_runs_issue",),
    ),
    TableSpec(
        name="run_leases",
        columns=(
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("owner_id", ("TEXT",)),
            ColumnSpec("epoch", ("BIGINT",)),
            ColumnSpec("expires_at", ("TIMESTAMP",)),
        ),
        primary_key=("run_id",),
        foreign_keys=(
            ForeignKeySpec(
                columns=("run_id",),
                referred_table="runs",
                referred_columns=("run_id",),
                ondelete="CASCADE",
            ),
        ),
        check_constraints=("run_leases_epoch_positive",),
    ),
    TableSpec(
        name="lease_takeover_authorisations",
        columns=(
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("observed_epoch", ("BIGINT",)),
            ColumnSpec("approved_by", ("TEXT",)),
            ColumnSpec("reason", ("TEXT",)),
            ColumnSpec("authorised_at", ("TIMESTAMP",)),
            ColumnSpec("consumed_epoch", ("BIGINT",), nullable=True),
        ),
        primary_key=("run_id", "observed_epoch"),
        foreign_keys=(
            ForeignKeySpec(
                columns=("run_id",),
                referred_table="runs",
                referred_columns=("run_id",),
                ondelete="CASCADE",
            ),
        ),
    ),
    TableSpec(
        name="external_side_effect_intents",
        columns=(
            ColumnSpec("intent_key", ("TEXT",)),
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("epoch", ("BIGINT",)),
            ColumnSpec("operation", ("TEXT",)),
            ColumnSpec("target_ref", ("TEXT",)),
            ColumnSpec("request_digest", ("TEXT",)),
            ColumnSpec("state", ("TEXT",)),
            ColumnSpec("outcome_detail", ("JSONB",), nullable=True),
            ColumnSpec("created_at", ("TIMESTAMP",)),
            ColumnSpec("resolved_at", ("TIMESTAMP",), nullable=True),
        ),
        primary_key=("intent_key",),
        foreign_keys=(
            ForeignKeySpec(
                columns=("run_id",),
                referred_table="runs",
                referred_columns=("run_id",),
                ondelete="CASCADE",
            ),
        ),
        indexes=("idx_side_effect_intents_run",),
    ),
    TableSpec(
        name="evidence",
        columns=(
            ColumnSpec("id", ("TEXT",)),
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("kind", ("TEXT",)),
            ColumnSpec("payload", ("JSONB",)),
            ColumnSpec("signature", ("TEXT",)),
            ColumnSpec("idempotency_key", ("TEXT",), nullable=True),
            ColumnSpec("event_timestamp", ("TIMESTAMP",)),
        ),
        primary_key=("id",),
        foreign_keys=(
            ForeignKeySpec(
                columns=("run_id",),
                referred_table="runs",
                referred_columns=("run_id",),
                ondelete="CASCADE",
            ),
        ),
        unique_constraints=(("run_id", "id"),),
        indexes=("idx_evidence_run", "idx_evidence_sig"),
    ),
    TableSpec(
        name="rate_limit_buckets",
        columns=(
            ColumnSpec("key", ("TEXT",)),
            ColumnSpec("hits", ("INTEGER",)),
            ColumnSpec("window_start", ("TIMESTAMP",)),
            ColumnSpec("window_seconds", ("INTEGER",)),
        ),
        # Composite primary key.  ADR-031 writes "key ... PRIMARY KEY" plus
        # "UNIQUE(key, window_start)"; the composite key expresses the
        # intended uniqueness (one bucket per key per window) and is the only
        # form consistent with the ADR's own rate-limiter algorithm and its
        # hourly pruner.  See the migration docstring for the full rationale.
        primary_key=("key", "window_start"),
    ),
    TableSpec(
        name="checkpoints",
        columns=(
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("checkpoint_type", ("TEXT",)),
            ColumnSpec("payload", ("JSONB",)),
            ColumnSpec("sequence", ("INTEGER",)),
            ColumnSpec("created_at", ("TIMESTAMP",)),
        ),
        primary_key=("run_id", "sequence"),
        foreign_keys=(
            ForeignKeySpec(
                columns=("run_id",),
                referred_table="runs",
                referred_columns=("run_id",),
                ondelete="CASCADE",
            ),
        ),
    ),
    TableSpec(
        name="seen_delivery_keys",
        columns=(
            ColumnSpec("delivery_id", ("TEXT",)),
            ColumnSpec("run_id", ("TEXT",)),
            ColumnSpec("seen_at", ("TIMESTAMP",)),
        ),
        primary_key=("delivery_id",),
    ),
)

#: The HA coordination schema contract.
HA_SCHEMA: tuple[TableSpec, ...] = _HA_SCHEMA

#: The same contract, keyed by table name.
#:
#: Later phases (lease management, CAS enforcement, readiness) look up a
#: single table's contract by name, so this mapping saves every caller from
#: writing its own search over :data:`HA_SCHEMA`.
HA_SCHEMA_BY_NAME: Mapping[str, TableSpec] = MappingProxyType(
    {table.name: table for table in HA_SCHEMA}
)

#: Every table the HA coordination schema is expected to contain.
HA_TABLE_NAMES: tuple[str, ...] = tuple(table.name for table in HA_SCHEMA)

#: Columns that must never take part in a time-dependent check constraint.
#:
#: See the module docstring: PostgreSQL only evaluates a check constraint when
#: the row is written, so constraining a lease expiry against wall-clock time
#: would block renewals and takeovers instead of policing them.
_TIME_DEPENDENT_GUARDED_COLUMNS = ("expires_at",)

#: Functions whose appearance in a check constraint indicates wall-clock coupling.
_TIME_DEPENDENT_FUNCTIONS = ("now()", "current_timestamp", "clock_timestamp", "localtimestamp")


def _rendered_type(column: Mapping[str, Any]) -> str:
    """Return the printable database type of an inspected column."""
    column_type = column.get("type")
    if column_type is None:
        return ""
    return str(column_type)


def _check_constraint_sql(check: Mapping[str, Any]) -> str:
    """Return the SQL text of an inspected check constraint."""
    for key in ("sqltext", "check_clause", "text"):
        value = check.get(key)
        if value:
            return str(value)
    return ""


def _is_time_dependent_check(sql_text: str) -> bool:
    """Return True when a check constraint depends on wall-clock time.

    The check is deliberately narrow: it only fires when the constraint
    mentions a guarded column *and* a time-dependent function.  A plain
    ``expires_at IS NOT NULL`` constraint is harmless.
    """
    lowered = sql_text.lower()
    if not any(column in lowered for column in _TIME_DEPENDENT_GUARDED_COLUMNS):
        return False
    return any(function in lowered for function in _TIME_DEPENDENT_FUNCTIONS)


def _validate_table(inspector: SchemaInspector, table: TableSpec) -> list[SchemaValidationIssue]:
    """Return every deviation of a single table from its contract."""
    issues: list[SchemaValidationIssue] = []

    try:
        columns = list(inspector.get_columns(table.name))
    except Exception as exc:  # pragma: no cover - defensive, driver specific
        raise SchemaInspectionError(f"could not inspect columns of {table.name}: {exc}") from exc

    observed: dict[str, Mapping[str, Any]] = {}
    for column in columns:
        name = str(column.get("name"))
        observed[name] = column

    for expected in table.columns:
        actual = observed.get(expected.name)
        if actual is None:
            issues.append(
                SchemaValidationIssue(
                    kind="missing_column",
                    table=table.name,
                    detail=f"expected column {expected.name!r} is missing",
                )
            )
            continue
        if not expected.type_matches(_rendered_type(actual)):
            issues.append(
                SchemaValidationIssue(
                    kind="column_type",
                    table=table.name,
                    detail=(
                        f"column {expected.name!r} has type "
                        f"{_rendered_type(actual)!r}, expected "
                        f"{' AND '.join(expected.type_tokens)!r}"
                    ),
                )
            )
        is_nullable = bool(actual.get("nullable", False))
        if is_nullable != expected.nullable:
            issues.append(
                SchemaValidationIssue(
                    kind="column_nullability",
                    table=table.name,
                    detail=(
                        f"column {expected.name!r} is "
                        f"{'nullable' if is_nullable else 'not null'}, expected "
                        f"{'nullable' if expected.nullable else 'not null'}"
                    ),
                )
            )

    try:
        pk = inspector.get_pk_constraint(table.name)
    except Exception as exc:  # pragma: no cover - defensive, driver specific
        raise SchemaInspectionError(f"could not inspect primary key of {table.name}: {exc}") from exc
    observed_pk = tuple(str(name) for name in (pk.get("constrained_columns") or ()))
    if observed_pk != table.primary_key:
        issues.append(
            SchemaValidationIssue(
                kind="primary_key",
                table=table.name,
                detail=f"primary key is {observed_pk or 'none'}, expected {table.primary_key}",
            )
        )

    try:
        foreign_keys = list(inspector.get_foreign_keys(table.name))
    except Exception as exc:  # pragma: no cover - defensive, driver specific
        raise SchemaInspectionError(f"could not inspect foreign keys of {table.name}: {exc}") from exc
    for expected_fk in table.foreign_keys:
        matched = False
        for fk in foreign_keys:
            constrained = tuple(str(name) for name in (fk.get("constrained_columns") or ()))
            referred = tuple(str(name) for name in (fk.get("referred_columns") or ()))
            if (
                constrained == expected_fk.columns
                and str(fk.get("referred_table")) == expected_fk.referred_table
                and referred == expected_fk.referred_columns
            ):
                matched = True
                if expected_fk.ondelete:
                    ondelete = str(fk.get("options", {}).get("ondelete", "") or "").upper()
                    if expected_fk.ondelete not in ondelete:
                        issues.append(
                            SchemaValidationIssue(
                                kind="foreign_key_delete_action",
                                table=table.name,
                                detail=(
                                    f"foreign key {expected_fk.columns} -> "
                                    f"{expected_fk.referred_table} has ON DELETE "
                                    f"{ondelete or 'NO ACTION'}, expected "
                                    f"{expected_fk.ondelete}"
                                ),
                            )
                        )
                break
        if not matched:
            issues.append(
                SchemaValidationIssue(
                    kind="missing_foreign_key",
                    table=table.name,
                    detail=(
                        f"expected foreign key {expected_fk.columns} -> "
                        f"{expected_fk.referred_table}{expected_fk.referred_columns} is missing"
                    ),
                )
            )

    if table.unique_constraints:
        try:
            uniques = list(inspector.get_unique_constraints(table.name))
        except Exception as exc:  # pragma: no cover - defensive, driver specific
            raise SchemaInspectionError(
                f"could not inspect unique constraints of {table.name}: {exc}"
            ) from exc
        observed_uniques = {
            tuple(str(name) for name in (unique.get("column_names") or ())) for unique in uniques
        }
        for expected_unique in table.unique_constraints:
            if expected_unique not in observed_uniques:
                issues.append(
                    SchemaValidationIssue(
                        kind="missing_unique_constraint",
                        table=table.name,
                        detail=f"expected UNIQUE{expected_unique} is missing",
                    )
                )

    try:
        checks = list(inspector.get_check_constraints(table.name))
    except Exception as exc:  # pragma: no cover - defensive, driver specific
        raise SchemaInspectionError(
            f"could not inspect check constraints of {table.name}: {exc}"
        ) from exc
    observed_check_names = {str(check.get("name")) for check in checks if check.get("name")}
    for expected_check in table.check_constraints:
        if expected_check not in observed_check_names:
            issues.append(
                SchemaValidationIssue(
                    kind="missing_check_constraint",
                    table=table.name,
                    detail=f"expected check constraint {expected_check!r} is missing",
                )
            )
    for check in checks:
        sql_text = _check_constraint_sql(check)
        if _is_time_dependent_check(sql_text):
            issues.append(
                SchemaValidationIssue(
                    kind="time_dependent_check",
                    table=table.name,
                    detail=(
                        f"check constraint {check.get('name')!r} depends on wall-clock time "
                        f"({sql_text!r}); PostgreSQL only evaluates check constraints on write, "
                        "so this freezes expired rows and blocks renewal or takeover"
                    ),
                )
            )

    if table.indexes:
        try:
            indexes = list(inspector.get_indexes(table.name))
        except Exception as exc:  # pragma: no cover - defensive, driver specific
            raise SchemaInspectionError(f"could not inspect indexes of {table.name}: {exc}") from exc
        observed_index_names = {str(index.get("name")) for index in indexes if index.get("name")}
        for expected_index in table.indexes:
            if expected_index not in observed_index_names:
                issues.append(
                    SchemaValidationIssue(
                        kind="missing_index",
                        table=table.name,
                        detail=f"expected index {expected_index!r} is missing",
                    )
                )

    return issues


def validate_ha_schema(
    inspector: SchemaInspector,
    *,
    schema: str | None = None,
) -> SchemaValidationReport:
    """Validate a live database against the HA coordination schema contract.

    Args:
        inspector: An object exposing the :class:`SchemaInspector` protocol.
            A SQLAlchemy ``Inspector`` satisfies it.
        schema: Optional PostgreSQL schema name to inspect.

    Returns:
        A :class:`SchemaValidationReport` listing every deviation found.  The
        report is returned rather than raised so callers can log all problems
        at once; use :meth:`SchemaValidationReport.require` to fail closed.
    """
    try:
        table_names = {str(name) for name in inspector.get_table_names()}
    except Exception as exc:
        raise SchemaInspectionError(f"could not list tables: {exc}") from exc

    issues: list[SchemaValidationIssue] = []
    for table in HA_SCHEMA:
        if table.name not in table_names:
            issues.append(
                SchemaValidationIssue(
                    kind="missing_table",
                    table=table.name,
                    detail="expected table is missing",
                )
            )
            continue
        issues.extend(_validate_table(inspector, table))

    return SchemaValidationReport(
        issues=tuple(issues),
        tables_checked=tuple(table.name for table in HA_SCHEMA),
    )
