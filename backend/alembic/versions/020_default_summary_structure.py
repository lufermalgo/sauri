"""Move unedited seeded default templates to the structured default instructions.

Only templates that still carry the exact seed v1 text are updated, so personal edits always
win. The upgrade bumps `version` and `updated_at`; summary requests keep their own
`instructions_snapshot`, so past summaries are unaffected. The downgrade restores the v1 text
only on rows that still carry the exact v2 text.
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op
from app.copy.templates_es import DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2

revision = "020_default_summary_structure"
down_revision = "019_failed_summary_request"
branch_labels = None
depends_on = None


def _seeded_ids(connection: sa.Connection, instructions: str) -> list[str]:
    """Templates holding `instructions` whose id is their owner's seeded default id."""
    rows = connection.execute(sa.text(
        "SELECT id, owner_user_id FROM summary_templates WHERE instructions = :instructions"
    ), {"instructions": instructions}).all()
    return [
        template_id for template_id, owner_id in rows
        if template_id == str(uuid5(NAMESPACE_URL, f"sauri:summary-default:2026-11-14:template:{owner_id}"))
    ]


def _rewrite(connection: sa.Connection, old: str, new: str, version_step: int) -> None:
    for template_id in _seeded_ids(connection, old):
        # The text condition makes a concurrent personal edit win and the step idempotent.
        connection.execute(sa.text(
            "UPDATE summary_templates SET instructions = :new, version = GREATEST(version + :step, 1), "
            "updated_at = CURRENT_TIMESTAMP WHERE id = :id AND instructions = :old"
        ), {"id": template_id, "old": old, "new": new, "step": version_step})


def upgrade() -> None:
    _rewrite(op.get_bind(), DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2, 1)


def downgrade() -> None:
    _rewrite(op.get_bind(), DEFAULT_INSTRUCTIONS_V2, DEFAULT_INSTRUCTIONS, -1)
