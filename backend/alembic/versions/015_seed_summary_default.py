"""Seed editable starter templates without changing personal ownership or preferences.

Downgrade deliberately retains user templates, defaults and categories, including
user edits and references from existing summaries; it never deletes user data.
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op
from app.copy.templates_es import DEFAULT_CATEGORY, DEFAULT_INSTRUCTIONS, DEFAULT_NAME

revision = "015_seed_summary_default"
down_revision = "014_meeting_summaries_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    owners = connection.execute(sa.text("SELECT id FROM users WHERE default_summary_template_id IS NULL")).scalars()
    for owner_id in owners:
        category_id, template_id = (
            str(uuid5(NAMESPACE_URL, f"sauri:summary-default:2026-11-14:{kind}:{owner_id}"))
            for kind in ("category", "template")
        )
        connection.execute(sa.text(
            "INSERT INTO template_categories (id, owner_user_id, name, created_at) "
            "VALUES (:id, :owner, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
        ), {"id": category_id, "owner": owner_id, "name": DEFAULT_CATEGORY})
        connection.execute(sa.text(
            "INSERT INTO summary_templates "
            "(id, owner_user_id, category_id, name, instructions, version, created_at, updated_at) "
            "VALUES (:id, :owner, :category, :name, :instructions, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        ), {
            "id": template_id, "owner": owner_id, "category": category_id, "name": DEFAULT_NAME,
            "instructions": DEFAULT_INSTRUCTIONS,
        })
        connection.execute(sa.text(
            "UPDATE users SET default_summary_template_id = :template WHERE id = :owner"
        ), {"template": template_id, "owner": owner_id})


def downgrade() -> None:
    # Data-only seed: retain editable templates and referenced artifacts on rollback.
    # Deleting them could destroy user edits or violate summary/outbox foreign keys.
    pass
