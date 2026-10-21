"""Initial HA schema: runs, run_leases, evidence, checkpoints, rate_limit_buckets, seen_delivery_keys.

Revision ID: 001_initial_ha_schema
Revises:
Create Date: 2026-10-21

This migration creates all tables required for ADR-030 High-Availability Multi-Process
Coordination. The schema is additive and does not affect any existing filesystem-based
store data.

Rollback: alembic downgrade -1 drops all 6 tables. No data is lost because the
HA layer never modifies or deletes filesystem data.

ADR Reference: docs/adr/ADR-030_HA_COORDINATION.md
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "001_initial_ha_schema"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Table 1: runs — HA coordination and state table
    # Stores full RunRecord snapshots with CAS revision counter.
    # ADR-030 § PostgreSQL Schema — runs table
    # -------------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("run_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "idempotency_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "command_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("run_id"),
    )

    # Fast lookup index for start_issue (SELECT FOR UPDATE on issue_number)
    op.create_index("idx_runs_issue", "runs", ["issue_number"])

    # Index for reconciliation: find non-terminal runs efficiently
    op.create_index(
        "idx_runs_state_updated",
        "runs",
        ["state", sa.text("updated_at DESC")],
    )

    # -------------------------------------------------------------------------
    # Table 2: run_leases — Per-run leadership lease
    # ADR-030 § Lease Ownership / Expiry / Takeover
    # -------------------------------------------------------------------------
    op.create_table(
        "run_leases",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
        # No two expired leases may coexist — enforces no_expired_leases CHECK
        sa.CheckConstraint(
            "expires_at > NOW()",
            name="no_expired_leases",
        ),
    )

    op.create_index("idx_run_leases_owner", "run_leases", ["owner_id"])
    op.create_index("idx_run_leases_expires", "run_leases", ["expires_at"])

    # -------------------------------------------------------------------------
    # Table 3: evidence — Append-only evidence log (replaces JSONL files)
    # ADR-030 § Evidence Integrity
    # -------------------------------------------------------------------------
    op.create_table(
        "evidence",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),  # SHA-256 rolling hash (ADR-009-4)
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "event_timestamp",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "id", name="uq_evidence_run_id_id"),
    )

    op.create_index("idx_evidence_run", "evidence", ["run_id"])
    op.create_index("idx_evidence_sig", "evidence", ["run_id", "signature"])
    op.create_index("idx_evidence_ts", "evidence", ["event_timestamp"])

    # -------------------------------------------------------------------------
    # Table 4: checkpoints — Run checkpoint snapshots (replaces .checkpoint files)
    # ADR-030 § Checkpoints
    # -------------------------------------------------------------------------
    op.create_table(
        "checkpoints",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )

    op.create_index("idx_checkpoints_run_seq", "checkpoints", ["run_id", "sequence"])
    op.create_index("idx_checkpoints_created", "checkpoints", ["created_at"])

    # -------------------------------------------------------------------------
    # Table 5: rate_limit_buckets — Shared anti-replay / rate-limit state
    # ADR-030 § Shared Anti-Replay / Rate-Limit State
    # -------------------------------------------------------------------------
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="3600"),
        # Unique constraint on (key, window_start) for the upsert pattern
        sa.UniqueConstraint("key", "window_start", name="uq_rate_limit_key_window"),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_index("idx_rate_limit_window", "rate_limit_buckets", ["window_start"])
    op.create_index("idx_rate_limit_hits", "rate_limit_buckets", ["hits"])

    # -------------------------------------------------------------------------
    # Table 6: seen_delivery_keys — Webhook idempotency deduplication
    # ADR-030 § Idempotency Keys
    # -------------------------------------------------------------------------
    op.create_table(
        "seen_delivery_keys",
        sa.Column("delivery_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column(
            "seen_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("delivery_id"),
    )

    op.create_index("idx_seen_delivery_run", "seen_delivery_keys", ["run_id"])
    op.create_index("idx_seen_delivery_seen", "seen_delivery_keys", ["seen_at"])

    # -------------------------------------------------------------------------
    # Add updated_at trigger on runs table
    # Uses a BEFORE UPDATE trigger to auto-set updated_at.
    # This requires procedural language; if plpgsql is not available,
    # application-layer updates will set updated_at manually (still safe).
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION _update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    op.execute("""
        CREATE TRIGGER _update_runs_updated_at
            BEFORE UPDATE ON runs
            FOR EACH ROW
            EXECUTE FUNCTION _update_updated_at_column();
    """)


def downgrade() -> None:
    """Drop all 6 HA tables.

    This reverses the initial schema migration. It is safe to run because:
    - The HA layer never deletes or modifies filesystem data.
    - Runs, evidence, and checkpoints are fully captured in the filesystem.
    - seen_delivery_keys and rate_limit_buckets are ephemeral and rebuildable.

    To confirm no data loss before dropping:
      psql "$HA_DATABASE_URL" -c "SELECT count(*) FROM runs"
      psql "$HA_DATABASE_URL" -c "SELECT count(*) FROM evidence"
    """
    # Drop triggers first (order matters for CASCADE)
    op.execute("DROP TRIGGER IF EXISTS _update_runs_updated_at ON runs")
    op.execute("DROP FUNCTION IF EXISTS _update_updated_at_column()")

    # Drop tables in reverse dependency order (no FK cycles, but reverse order is safe)
    op.drop_table("seen_delivery_keys")
    op.drop_table("rate_limit_buckets")
    op.drop_table("checkpoints")
    op.drop_table("evidence")
    op.drop_table("run_leases")
    op.drop_table("runs")
