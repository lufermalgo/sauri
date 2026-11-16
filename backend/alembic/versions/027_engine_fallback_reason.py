"""Record why the local engine answered in place of the chosen provider (U4.3, #1117)."""

import sqlalchemy as sa

from alembic import op

revision = "027_engine_fallback_reason"
down_revision = "026_engine_providers"
branch_labels = None
depends_on = None

PROVENANCE_TABLES = ("transcripts", "diarizations", "meeting_summaries")


def upgrade() -> None:
    # The error class only (for example provider_unavailable): never content, keys or paths.
    for table in PROVENANCE_TABLES:
        op.add_column(table, sa.Column("engine_fallback_reason", sa.String(64), nullable=True))


def downgrade() -> None:
    for table in reversed(PROVENANCE_TABLES):
        op.drop_column(table, "engine_fallback_reason")
