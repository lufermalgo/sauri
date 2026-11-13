"""Join independent 014 processing-revision and meeting-summary histories.

Both migrations are additive siblings of 013. Neither schema nor data should
be rewritten or downgraded by this mergepoint; Alembic applies each parent once.
"""

from collections.abc import Sequence

revision: str = "015_merge_processing_summaries"
down_revision: tuple[str, str] = ("014_processing_revisions", "014_meeting_summaries_templates")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
