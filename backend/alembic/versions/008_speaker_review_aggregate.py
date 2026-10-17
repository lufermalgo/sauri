"""Speaker review aggregate and per-speaker disposition items.

Adds `speaker_reviews` (one recording/revision-scoped aggregate with a derived
status) and `speaker_review_items` (one immutable speaker key per initial
diarization speaker, with an optional explicit disposition). No existing table
or row is altered; identity samples, submissions and excerpt refs belong to
later tasks.

Revision ID: 008_speaker_review_aggregate
Revises: 007_rename_schema_to_english
Create Date: 2026-10-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_speaker_review_aggregate"
down_revision: str | None = "007_rename_schema_to_english"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "speaker_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("processing_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "meeting_id", "processing_revision", name="uq_speaker_review_revision"
        ),
    )

    op.create_table(
        "speaker_review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("speaker_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("speaker_key", sa.String(128), nullable=False),
        sa.Column("current_label", sa.String(64), nullable=False),
        sa.Column("disposition", sa.String(16), nullable=True),
        sa.Column("chosen_label", sa.String(64), nullable=True),
        sa.Column("attribution_state", sa.String(16), nullable=False, server_default="uncertain"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("review_id", "speaker_key", name="uq_speaker_review_item_speaker"),
    )


def downgrade() -> None:
    op.drop_table("speaker_review_items")
    op.drop_table("speaker_reviews")
