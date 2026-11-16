"""When a recording was actually made, apart from when Sauri received it (#1157)."""

import sqlalchemy as sa

from alembic import op

revision = "029_meeting_recorded_at"
down_revision = "028_auth_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True))
    # A short code for where the value came from: capture | file_metadata | file_modified | received.
    op.add_column("meetings", sa.Column("recorded_at_source", sa.String(32), nullable=True))
    # Stored objects cannot be re-probed from a migration: existing rows keep the date Sauri received them.
    # The `python -m app.thumbnails.recorded_at` command upgrades them later from the file metadata.
    op.execute("UPDATE meetings SET recorded_at = created_at, recorded_at_source = 'received'")


def downgrade() -> None:
    op.drop_column("meetings", "recorded_at_source")
    op.drop_column("meetings", "recorded_at")
