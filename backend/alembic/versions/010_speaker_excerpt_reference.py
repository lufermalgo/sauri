"""Persist opaque speaker-excerpt references on review items.

Revision ID: 010_speaker_excerpt_reference
Revises: 009_recording_media_sources, 009_speaker_review_idempotency_receipts
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_speaker_excerpt_reference"
down_revision: tuple[str, str] = (
    "009_recording_media_sources",
    "009_speaker_review_idempotency_receipts",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "speaker_review_items",
        sa.Column("excerpt_ref", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("speaker_review_items", "excerpt_ref")
