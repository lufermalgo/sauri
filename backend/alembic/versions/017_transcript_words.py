"""Word-level transcript timestamps and per-diarization word speaker attribution.

Both tables are derived from engine output and are removed with their transcript
(ON DELETE CASCADE); downgrade drops them.
"""

import sqlalchemy as sa

from alembic import op

revision = "017_transcript_words"
down_revision = "016_summary_failure_cause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcript_words",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "transcript_id", sa.String(36),
            sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("timing_repaired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("transcript_id", "sequence", name="uq_transcript_word_sequence"),
    )
    op.create_index(
        "ix_transcript_words_transcript_start", "transcript_words", ["transcript_id", "start_ms"]
    )
    op.create_table(
        "word_speaker_assignments",
        sa.Column(
            "diarization_id", sa.String(36),
            sa.ForeignKey("diarizations.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "word_id", sa.String(36),
            sa.ForeignKey("transcript_words.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "speaker_id", sa.String(36),
            sa.ForeignKey("speakers.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "state IN ('assigned', 'ambiguous', 'unassigned')",
            name="ck_word_speaker_assignments_state_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("word_speaker_assignments")
    op.drop_index("ix_transcript_words_transcript_start", table_name="transcript_words")
    op.drop_table("transcript_words")
