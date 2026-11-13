"""Allow linkless meetings and persist staged-object cleanup tasks.

Revision ID: 011_linkless_meeting_pending_object_deletions
Revises: 010_speaker_excerpt_reference
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_linkless_cleanup"
down_revision = "010_speaker_excerpt_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "meetings",
        "meet_link",
        existing_type=sa.String(length=512),
        nullable=True,
    )
    op.create_table(
        "pending_object_deletions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cleanup_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("object_ref", sa.String(length=2048), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cleanup_scope_hash",
            "object_ref",
            name="uq_pending_object_deletion_scope_ref",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    pending_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM pending_object_deletions")
    ).scalar_one()
    if pending_count:
        raise RuntimeError(
            "Cannot downgrade while pending object cleanup tasks exist."
        )

    null_link_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM meetings WHERE meet_link IS NULL")
    ).scalar_one()
    if null_link_count:
        raise RuntimeError("Cannot downgrade while meetings have null Meet links.")

    op.drop_table("pending_object_deletions")
    op.alter_column(
        "meetings",
        "meet_link",
        existing_type=sa.String(length=512),
        nullable=False,
    )
