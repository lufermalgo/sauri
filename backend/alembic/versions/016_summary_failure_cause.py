"""Persist categorized summary request failures without changing event payloads."""

import sqlalchemy as sa

from alembic import op

revision = "016_summary_failure_cause"
down_revision = "015_seed_summary_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("summary_request_outbox", sa.Column("failure_cause", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("summary_request_outbox", "failure_cause")
