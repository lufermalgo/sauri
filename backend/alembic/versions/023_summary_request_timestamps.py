"""Record when a summary request was accepted, started and settled."""

import sqlalchemy as sa

from alembic import op

revision = "023_summary_request_timestamps"
down_revision = "022_recording_thumbnail"
branch_labels = None
depends_on = None

TABLE = "summary_request_outbox"
COLUMNS = ("requested_at", "started_at", "finished_at")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    # Legacy rows have no acceptance time; the delivery time is the closest recorded moment.
    op.execute(f"UPDATE {TABLE} SET requested_at = delivered_at WHERE delivered_at IS NOT NULL")


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column)
