"""Final source-referenced output, retained/deleted with its diarization revision.

No words, raw acoustic timelines, audio or scores are stored by this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014_final_presentation"
down_revision = "013_manual_recovery_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("diarizations", sa.Column("prepared_result", sa.JSON(), nullable=True))
    op.add_column("diarizations", sa.Column("presentation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("diarizations", "presentation")
    op.drop_column("diarizations", "prepared_result")
