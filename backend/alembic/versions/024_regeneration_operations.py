"""Audit trail for explicit stage regeneration (#1053)."""

import sqlalchemy as sa

from alembic import op

revision = "024_regeneration_operations"
down_revision = "023_summary_request_timestamps"
branch_labels = None
depends_on = None

TABLE = "regeneration_operations"
ACTIVE = "status IN ('accepted', 'running')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("cascade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "template_id", sa.String(36), sa.ForeignKey("summary_templates.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("parent_operation_id", sa.String(36), nullable=True),
        sa.Column("processing_generation", sa.Integer(), nullable=True),
        sa.Column("diarization_revision", sa.Integer(), nullable=True),
        sa.Column("summary_event_id", sa.String(36), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_cause", sa.String(64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "requested_by", "meeting_id", "idempotency_key", name="uq_regeneration_idempotency_scope"
        ),
        sa.CheckConstraint("stage IN ('transcription', 'speakers', 'summary')", name="ck_regeneration_stage_valid"),
        sa.CheckConstraint(
            "status IN ('accepted', 'running', 'succeeded', 'failed')", name="ck_regeneration_status_valid"
        ),
    )
    op.create_index(
        "uq_regeneration_one_active_per_meeting",
        TABLE,
        ["meeting_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE),
    )
    op.create_index("ix_regeneration_operations_meeting_requested", TABLE, ["meeting_id", "requested_at"])


def downgrade() -> None:
    op.drop_index("ix_regeneration_operations_meeting_requested", table_name=TABLE)
    op.drop_index("uq_regeneration_one_active_per_meeting", table_name=TABLE)
    op.drop_table(TABLE)
