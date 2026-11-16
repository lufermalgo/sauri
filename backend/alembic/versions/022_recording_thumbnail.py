"""Track the library preview frame of each recording."""

import sqlalchemy as sa

from alembic import op

revision = "022_recording_thumbnail"
down_revision = "021_default_summary_legacy_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_recordings", sa.Column("thumbnail_ref", sa.String(1024), nullable=True))
    op.add_column("session_recordings", sa.Column("thumbnail_state", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_session_recordings_thumbnail_state",
        "session_recordings",
        "thumbnail_state IS NULL OR thumbnail_state IN ('ready', 'audio_only', 'unavailable')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_session_recordings_thumbnail_state", "session_recordings", type_="check")
    op.drop_column("session_recordings", "thumbnail_ref")
    op.drop_column("session_recordings", "thumbnail_state")
