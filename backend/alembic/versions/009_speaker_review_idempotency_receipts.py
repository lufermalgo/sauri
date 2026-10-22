"""Persist idempotency receipts for speaker-review disposition writes.

Revision ID: 009_speaker_review_idempotency_receipts
Revises: 008_speaker_review_aggregate
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_speaker_review_idempotency_receipts"
down_revision: str | None = "008_speaker_review_aggregate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=39),
    )
    op.create_table(
        "speaker_review_idempotency_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("speaker_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("speaker_review_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.UniqueConstraint("review_id", "idempotency_key", name="uq_review_idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("speaker_review_idempotency_receipts")
