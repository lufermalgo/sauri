"""Add content-free durable manual recovery coordination and outbox tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_manual_recovery_persistence"
down_revision = "012_diarization_generations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_processing_claims",
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_id", sa.String(36), nullable=True),
        sa.Column("claim_kind", sa.String(32), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("meeting_id"),
        sa.UniqueConstraint("meeting_id", name="uq_processing_claim_meeting_id"),
    )
    op.create_table(
        "meeting_recovery_operations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("processing_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("preservation_snapshot_digest", sa.String(64), nullable=True),
        sa.Column("preservation_counts", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id", "meeting_id", "idempotency_key",
            name="uq_recovery_operation_idempotency_scope",
        ),
        sa.CheckConstraint(
            "preservation_counts IS NULL OR "
            "CAST(preservation_counts AS TEXT) = '{}'",
            name="ck_recovery_operation_empty_preservation_counts",
        ),
    )
    op.create_index(
        "ix_meeting_recovery_operations_meeting_id",
        "meeting_recovery_operations",
        ["meeting_id"],
    )
    op.create_table(
        "meeting_recovery_outbox",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("job_identifiers", sa.JSON(), nullable=False),
        sa.Column("processing_generation", sa.Integer(), nullable=False),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["meeting_recovery_operations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_recovery_outbox_operation_id"),
        sa.CheckConstraint(
            "CAST(job_identifiers AS TEXT) = '{}'",
            name="ck_recovery_outbox_empty_job_identifiers",
        ),
    )
    op.create_table(
        "manual_recovery_pilot_gate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("allowed_meeting_id", sa.String(36), nullable=True),
        sa.Column("authorized_by", sa.String(36), nullable=True),
        sa.Column("pilot_operation_id", sa.String(36), nullable=True),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_actor_id", sa.String(36), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_artifact_snapshot_match", sa.Boolean(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_manual_recovery_pilot_gate_singleton"),
        sa.ForeignKeyConstraint(
            ["allowed_meeting_id"], ["meetings.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["authorized_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["pilot_operation_id"], ["meeting_recovery_operations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["verification_actor_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_operation_id", name="uq_recovery_pilot_operation_id"),
    )
    op.create_index(
        "ix_meeting_recovery_outbox_delivery_status",
        "meeting_recovery_outbox",
        ["delivery_status", "next_attempt_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM meeting_recovery_operations LIMIT 1")).first():
        raise RuntimeError(
            "Manual recovery history exists; retain it and use a forward-compatible rollback."
        )

    op.drop_index(
        "ix_meeting_recovery_outbox_delivery_status", table_name="meeting_recovery_outbox"
    )
    op.drop_table("manual_recovery_pilot_gate")
    op.drop_table("meeting_recovery_outbox")
    op.drop_index(
        "ix_meeting_recovery_operations_meeting_id",
        table_name="meeting_recovery_operations",
    )
    op.drop_table("meeting_recovery_operations")
    op.drop_table("meeting_processing_claims")
