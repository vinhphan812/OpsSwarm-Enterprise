"""Initial HA coordination schema (ADR-031).

Revision ID: 001_initial_ha_schema
Revises:
Create Date: 2026-10-23

Creates the eight PostgreSQL tables that back the OpsSwarm HA coordination
contract described in ``docs/adr/ADR-031_HA_COORDINATION.md``:

=========================== ==================================================
``runs``                     Durable run snapshot plus revision counter
``run_leases``               Leadership lease with durable epoch fencing
``lease_takeover_authorisations``  Audited operator failover authorisations
``external_side_effect_intents``   Intent/outcome records for GitHub writes
``evidence``                 Append-only SHA-256 chained evidence log
``rate_limit_buckets``       Shared cross-process rate-limit state
``checkpoints``              Durable per-run resume points
``seen_delivery_keys``       Webhook delivery idempotency keys
=========================== ==================================================

Design notes that are easy to get wrong
---------------------------------------

**No time-dependent check constraint on ``run_leases``.**  ADR-031 explicitly
forbids ``CHECK (expires_at > NOW())``.  PostgreSQL evaluates a check
constraint only when the row is written, never as wall-clock time advances, so
such a constraint would become false the moment the lease expired and would
then reject every subsequent ``UPDATE`` of that row -- including the renewal
and the takeover it was meant to police.  Expiry is instead evaluated
dynamically inside the acquisition transaction, using PostgreSQL server time
(``NOW()``) together with ``SELECT ... FOR UPDATE``.  The only check constraint
on the table is ``run_leases_epoch_positive``, which is time-independent.

**Epoch, not a bare fencing token.**  ``run_leases.epoch`` is the durable,
strictly increasing fencing token.  The first owner receives epoch ``1``; a
renewal by the same ``owner_id`` preserves the epoch; a takeover increments it
in the same row-locking transaction that changes ``owner_id``.  A holder of a
stale epoch is rejected on every protected write.

**``rate_limit_buckets`` uses a composite primary key.**  ADR-031 states both
``PRIMARY KEY`` and ``UNIQUE(key, window_start)`` for this table.  A primary
key on ``key`` alone would make it impossible to keep two windows for the same
key, and it would break the shared rate limiter's
``INSERT ... ON CONFLICT (key, window_start) DO UPDATE`` upsert: a new window
for a live key would raise a primary-key violation instead of being handled by
the conflict clause.  The composite primary key ``(key, window_start)``
expresses the intended uniqueness -- one bucket per key per window -- and makes
the documented upsert correct.

Rollback
--------
``downgrade`` drops every table this revision created, in dependency order.
The HA layer is additive: it never destroys the filesystem run data, so
reverting to the legacy filesystem store (``ha.enabled = false``) leaves the
existing ``runtime-data/`` records untouched.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001_initial_ha_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the HA coordination schema."""
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        # Full RunRecord.model_dump() snapshot; the durable source of truth
        # that a resuming standby reloads.
        sa.Column("run_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Optimistic-locking counter. Every mutating path uses
        # "UPDATE ... WHERE revision = :expected_revision" (ADR-031 CAS).
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "idempotency_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "command_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_runs"),
    )
    op.create_index("idx_runs_issue", "runs", ["issue_number"])

    op.create_table(
        "run_leases",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        # Durable, strictly increasing fencing token (ADR-031 epoch fencing).
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_run_leases"),
        # Time-independent constraint only.  A time-dependent
        # "expires_at > NOW()" check is deliberately NOT present: PostgreSQL
        # evaluates check constraints on write only, so it would freeze an
        # expired row and block renewal and takeover.
        sa.CheckConstraint("epoch > 0", name="run_leases_epoch_positive"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_run_leases_run_id_runs",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "lease_takeover_authorisations",
        sa.Column("run_id", sa.Text(), nullable=False),
        # The lease epoch observed when the operator authorised the takeover.
        # Binding the authorisation to the observed epoch prevents an
        # authorisation issued for one lease generation from being applied to a
        # later one.
        sa.Column("observed_epoch", sa.BigInteger(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "authorised_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # The epoch actually granted when the takeover happened, NULL while the
        # authorisation is still unconsumed.
        sa.Column("consumed_epoch", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint(
            "run_id",
            "observed_epoch",
            name="pk_lease_takeover_authorisations",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_lease_takeover_authorisations_run_id_runs",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "external_side_effect_intents",
        sa.Column("intent_key", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        # The lease epoch of the leader that issued the intent.
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        # INTENDED | CONFIRMED | FAILED | AMBIGUOUS
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("outcome_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("intent_key", name="pk_external_side_effect_intents"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_external_side_effect_intents_run_id_runs",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_side_effect_intents_run",
        "external_side_effect_intents",
        ["run_id", "state"],
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # SHA-256 rolling hash (ADR-009-4); the evidence chain integrity anchor.
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "event_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
        sa.UniqueConstraint("run_id", "id", name="uq_evidence_run_id_id"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_evidence_run_id_runs",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_evidence_run", "evidence", ["run_id"])
    op.create_index("idx_evidence_sig", "evidence", ["run_id", "signature"])

    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "window_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3600"),
        ),
        # Composite primary key: one bucket per key per window. See the module
        # docstring for why the key alone cannot be the primary key.
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_limit_buckets"),
    )

    op.create_table(
        "checkpoints",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_checkpoints"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_checkpoints_run_id_runs",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "seen_delivery_keys",
        sa.Column("delivery_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("delivery_id", name="pk_seen_delivery_keys"),
    )


def downgrade() -> None:
    """Drop the HA coordination schema."""
    op.drop_table("seen_delivery_keys")
    op.drop_table("checkpoints")
    op.drop_table("rate_limit_buckets")
    op.drop_index("idx_evidence_sig", table_name="evidence")
    op.drop_index("idx_evidence_run", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(
        "idx_side_effect_intents_run",
        table_name="external_side_effect_intents",
    )
    op.drop_table("external_side_effect_intents")
    op.drop_table("lease_takeover_authorisations")
    op.drop_table("run_leases")
    op.drop_index("idx_runs_issue", table_name="runs")
    op.drop_table("runs")
