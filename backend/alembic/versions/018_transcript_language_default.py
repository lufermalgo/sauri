"""Use the base Spanish language code for future transcripts only."""

import sqlalchemy as sa

from alembic import op

revision = "018_transcript_language_default"
down_revision = "017_transcript_words"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("transcripts", "language", existing_type=sa.String(16), server_default="es")


def downgrade() -> None:
    op.alter_column("transcripts", "language", existing_type=sa.String(16), server_default="es-CO")
