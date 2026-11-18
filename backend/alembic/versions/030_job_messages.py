"""Durable PostgreSQL job queue (#1201)."""

import sqlalchemy as sa

from alembic import op

revision = "030_job_messages"
down_revision = "029_meeting_recorded_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "job_messages_ready", "job_messages", ["topic", "available_at"],
        postgresql_where=sa.text("locked_until IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("job_messages_ready", table_name="job_messages")
    op.drop_table("job_messages")
