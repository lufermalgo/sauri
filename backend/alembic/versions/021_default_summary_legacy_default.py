"""Move the unedited legacy default template to the structured default instructions.

Migration 020 only reaches templates whose id is the owner's seeded id. A default template
created by an earlier mechanism has another id, so it kept the v1 text. This step updates
templates that are some user's default, keep the starter name and still carry the exact v1
text; personal edits always win. Seeded ids are left to migration 020 so both steps compose in
either direction. The upgrade bumps `version` and `updated_at`; past summaries keep their own
`instructions_snapshot`. The downgrade restores v1 only on rows that still carry the exact v2 text.
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op
from app.copy.templates_es import DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2, DEFAULT_NAME

revision = "021_default_summary_legacy_default"
down_revision = "020_default_summary_structure"
branch_labels = None
depends_on = None


def _legacy_default_ids(connection: sa.Connection, instructions: str) -> list[str]:
    """Starter-named templates holding `instructions` that are a user's default, minus seeded ids."""
    rows = connection.execute(sa.text(
        "SELECT t.id, t.owner_user_id FROM summary_templates t "
        "WHERE t.instructions = :instructions AND t.name = :name "
        "AND EXISTS (SELECT 1 FROM users u WHERE u.default_summary_template_id = t.id)"
    ), {"instructions": instructions, "name": DEFAULT_NAME}).all()
    return [
        template_id for template_id, owner_id in rows
        if template_id != str(uuid5(NAMESPACE_URL, f"sauri:summary-default:2026-11-14:template:{owner_id}"))
    ]


def _rewrite(connection: sa.Connection, old: str, new: str, version_step: int) -> None:
    for template_id in _legacy_default_ids(connection, old):
        # The text condition makes a concurrent personal edit win and the step idempotent.
        connection.execute(sa.text(
            "UPDATE summary_templates SET instructions = :new, version = GREATEST(version + :step, 1), "
            "updated_at = CURRENT_TIMESTAMP WHERE id = :id AND instructions = :old"
        ), {"id": template_id, "old": old, "new": new, "step": version_step})


def upgrade() -> None:
    _rewrite(op.get_bind(), DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2, 1)


def downgrade() -> None:
    _rewrite(op.get_bind(), DEFAULT_INSTRUCTIONS_V2, DEFAULT_INSTRUCTIONS, -1)
