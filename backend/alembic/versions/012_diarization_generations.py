"""Version diarization attempts and scope assignments to their generation."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_diarization_generations"
down_revision = "011_linkless_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _upgrade_sqlite()
    elif bind.dialect.name == "postgresql":
        _upgrade_postgresql()
    else:
        raise RuntimeError(f"Unsupported database dialect: {bind.dialect.name}")


def _upgrade_postgresql() -> None:
    op.add_column(
        "diarizations",
        sa.Column("processing_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "diarizations",
        sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "speaker_assignments",
        sa.Column("overlap_ms", sa.Integer(), nullable=True),
    )
    op.execute(sa.text("UPDATE diarizations SET is_legacy = true"))
    op.alter_column(
        "diarizations",
        "provider",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.alter_column(
        "diarizations",
        "speaker_count",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default="0",
    )

    op.drop_constraint("uq_diarization_meeting_id", "diarizations", type_="unique")
    op.create_unique_constraint(
        "uq_diarization_meeting_revision",
        "diarizations",
        ["meeting_id", "processing_revision"],
    )
    op.drop_constraint(
        "uq_speaker_assignment_turn_id", "speaker_assignments", type_="unique"
    )
    op.create_unique_constraint(
        "uq_speaker_assignment_diarization_turn",
        "speaker_assignments",
        ["diarization_id", "turn_id"],
    )


def _upgrade_sqlite() -> None:
    # SQLite rebuilds tables to change UNIQUE constraints. Preserve child rows
    # explicitly while the parent table is rebuilt with foreign keys enabled.
    op.execute(
        sa.text(
            "CREATE TEMP TABLE _t6_speakers AS "
            "SELECT id, diarization_id, raw_label, label, sequence FROM speakers"
        )
    )
    op.execute(
        sa.text(
            "CREATE TEMP TABLE _t6_assignments AS "
            "SELECT id, diarization_id, turn_id, speaker_id FROM speaker_assignments"
        )
    )
    op.execute(sa.text("DELETE FROM speaker_assignments"))
    op.execute(sa.text("DELETE FROM speakers"))

    with op.batch_alter_table("diarizations", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_diarization_meeting_id", type_="unique")
        batch_op.add_column(
            sa.Column("processing_revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.alter_column(
            "provider", existing_type=sa.String(length=128), nullable=True
        )
        batch_op.alter_column(
            "speaker_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="0",
        )
        batch_op.create_unique_constraint(
            "uq_diarization_meeting_revision", ["meeting_id", "processing_revision"]
        )

    op.execute(sa.text("UPDATE diarizations SET is_legacy = true"))

    with op.batch_alter_table("speaker_assignments", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_speaker_assignment_turn_id", type_="unique")
        batch_op.add_column(sa.Column("overlap_ms", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_speaker_assignment_diarization_turn", ["diarization_id", "turn_id"]
        )

    op.execute(
        sa.text(
            "INSERT INTO speakers (id, diarization_id, raw_label, label, sequence) "
            "SELECT id, diarization_id, raw_label, label, sequence FROM _t6_speakers"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO speaker_assignments "
            "(id, diarization_id, turn_id, speaker_id, overlap_ms) "
            "SELECT id, diarization_id, turn_id, speaker_id, NULL FROM _t6_assignments"
        )
    )
    op.execute(sa.text("DROP TABLE _t6_assignments"))
    op.execute(sa.text("DROP TABLE _t6_speakers"))


def downgrade() -> None:
    raise RuntimeError(
        "Diarization generations cannot be downgraded without losing data."
    )
