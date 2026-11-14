"""Represent failed automatic acceptance without inventing a template snapshot."""

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "019_failed_summary_request"
down_revision = "018_transcript_language_default"
branch_labels = None
depends_on = None

COLUMNS: dict[str, sa.types.TypeEngine[Any]] = {
    "template_id": sa.String(36),
    "template_version": sa.Integer(),
    "instructions_snapshot": sa.Text(),
}
CONSTRAINT = "ck_summary_request_snapshot_or_failed"


def upgrade() -> None:
    for column, data_type in COLUMNS.items():
        op.alter_column("summary_request_outbox", column, existing_type=data_type, nullable=True)
    op.create_check_constraint(
        CONSTRAINT,
        "summary_request_outbox",
        "(template_id IS NOT NULL AND template_version IS NOT NULL AND instructions_snapshot IS NOT NULL) OR "
        "(status = 'failed' AND template_id IS NULL AND template_version IS NULL AND instructions_snapshot IS NULL)",
    )


def downgrade() -> None:
    missing = op.get_bind().scalar(sa.text("SELECT count(*) FROM summary_request_outbox WHERE template_id IS NULL"))
    if missing:
        raise RuntimeError("Cannot remove failed acceptance support while requests lack a template snapshot")
    op.drop_constraint(CONSTRAINT, "summary_request_outbox", type_="check")
    for column, data_type in COLUMNS.items():
        op.alter_column("summary_request_outbox", column, existing_type=data_type, nullable=False)
