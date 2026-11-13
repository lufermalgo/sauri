"""Persist personal templates, summary requests, and generated summary artifacts.

Revision ID: 014_meeting_summaries_templates
Revises: 013_manual_recovery_persistence
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014_meeting_summaries_templates"
down_revision: str | None = "013_manual_recovery_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "template_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_template_categories_owner_user_id", "template_categories", ["owner_user_id"])
    op.create_table(
        "summary_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("template_categories.id"), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_summary_templates_owner_user_id", "summary_templates", ["owner_user_id"])
    op.create_table(
        "summary_request_outbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", sa.String(36), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("summary_templates.id"), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("instructions_snapshot", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("transcript_id", "generation", name="uq_summary_request_transcript_generation"),
    )
    op.create_table(
        "processed_summary_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "meeting_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", sa.String(36), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("summary_templates.id"), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("key_points_json", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_meeting_summary_event_id"),
        sa.UniqueConstraint("transcript_id", "generation", name="uq_meeting_summary_transcript_generation"),
    )
    # Break the users ↔ summary_templates FK cycle explicitly, after both tables exist.
    op.add_column("users", sa.Column("default_summary_template_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_users_default_summary_template_id_summary_templates",
        "users", "summary_templates", ["default_summary_template_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_default_summary_template_id_summary_templates", "users", type_="foreignkey")
    op.drop_column("users", "default_summary_template_id")
    op.drop_table("meeting_summaries")
    op.drop_table("processed_summary_events")
    op.drop_table("summary_request_outbox")
    op.drop_index("ix_summary_templates_owner_user_id", table_name="summary_templates")
    op.drop_table("summary_templates")
    op.drop_index("ix_template_categories_owner_user_id", table_name="template_categories")
    op.drop_table("template_categories")
