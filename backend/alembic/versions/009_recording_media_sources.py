"""Persist explicit recording source inventory and video capture evidence.

Revision ID: 009_recording_media_sources
Revises: 008_speaker_review_aggregate
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "009_recording_media_sources"
down_revision: str | None = "008_speaker_review_aggregate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_recordings",
        sa.Column("video_presence", sa.String(length=16), nullable=False, server_default="unknown"),
    )
    op.create_table(
        "recording_media_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "recording_id",
            sa.String(length=36),
            sa.ForeignKey("session_recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("object_ref", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("video_offset_ms", sa.Integer(), nullable=True),
        sa.Column("quality_label", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "recording_id", "kind", "object_ref", name="uq_recording_media_source_ref"
        ),
    )

    connection = op.get_bind()
    recordings = connection.execute(
        sa.text("SELECT id, audio_ref, video_ref FROM session_recordings")
    ).mappings()
    sources = []
    for recording in recordings:
        sources.append(
            {
                "id": str(uuid.uuid4()),
                "recording_id": recording["id"],
                "kind": "audio",
                "object_ref": recording["audio_ref"],
                "quality_label": "Original",
            }
        )
        if recording["video_ref"] is not None:
            sources.append(
                {
                    "id": str(uuid.uuid4()),
                    "recording_id": recording["id"],
                    "kind": "video",
                    "object_ref": recording["video_ref"],
                    "quality_label": "Original",
                }
            )
    if sources:
        connection.execute(
            sa.table(
                "recording_media_sources",
                sa.column("id", sa.String),
                sa.column("recording_id", sa.String),
                sa.column("kind", sa.String),
                sa.column("object_ref", sa.String),
                sa.column("quality_label", sa.String),
            ).insert(),
            sources,
        )


def downgrade() -> None:
    op.drop_table("recording_media_sources")
    op.drop_column("session_recordings", "video_presence")
