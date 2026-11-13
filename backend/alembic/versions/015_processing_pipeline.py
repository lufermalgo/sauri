"""Merge independent summary and processing branches; persist exact stage leases."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "015_processing_pipeline"
down_revision: tuple[str, str] = ("014_processing_revisions", "014_meeting_summaries_templates")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "processing_revision_id",
            sa.String(36),
            sa.ForeignKey("processing_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.UniqueConstraint("processing_revision_id", "stage", name="uq_processing_stage_revision_stage"),
    )


def downgrade() -> None:
    op.drop_table("processing_stages")
