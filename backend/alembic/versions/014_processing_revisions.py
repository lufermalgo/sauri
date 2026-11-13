"""Persist exact recording revisions without declaring legacy results review-ready."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "014_processing_revisions"
# The summaries migration is already on main; preserve its schema and data before
# installing the processing-revision tables on the stacked speaker-review branch.
down_revision = "014_meeting_summaries_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recording_id", sa.String(36), sa.ForeignKey("session_recordings.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(256), nullable=True),
        sa.Column("request_fingerprint", sa.String(128), nullable=True),
        sa.Column("admitted_active_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recording_id", "revision", name="uq_processing_revision_number"),
        sa.UniqueConstraint("recording_id", "request_id", name="uq_processing_revision_request"),
    )
    op.create_table(
        "recording_processing_states",
        sa.Column(
            "recording_id", sa.String(36), sa.ForeignKey("session_recordings.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "active_processing_revision_id", sa.String(36), sa.ForeignKey("processing_revisions.id"), nullable=True
        ),
        sa.Column("in_flight_revision_id", sa.String(36), sa.ForeignKey("processing_revisions.id"), nullable=True),
        sa.Column(
            "legacy_compatibility_revision_id", sa.String(36), sa.ForeignKey("processing_revisions.id"), nullable=True
        ),
    )
    op.create_table(
        "processing_revision_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recording_id",
            sa.String(36),
            sa.ForeignKey("session_recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processing_revision_id",
            sa.String(36),
            sa.ForeignKey("processing_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("processing_revision_id", "event_type", name="uq_revision_outbox_event"),
    )
    op.add_column("transcripts", sa.Column("processing_revision_id", sa.String(36), nullable=True))
    op.add_column("diarizations", sa.Column("processing_revision_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_transcript_processing_revision", "transcripts", "processing_revisions", ["processing_revision_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_diarization_processing_revision", "diarizations", "processing_revisions", ["processing_revision_id"], ["id"]
    )

    connection = op.get_bind()
    # The migration records what exists, not what is ready. Legacy stage rows may be
    # partial or failed, and no review/excerpts can be inferred from their presence.
    recordings = connection.execute(sa.text("SELECT id, meeting_id FROM session_recordings")).all()
    for recording_id, meeting_id in recordings:
        numbers = (
            connection.execute(
                sa.text(
                    "SELECT 1 AS revision FROM transcripts WHERE meeting_id=:meeting "
                    "UNION SELECT processing_revision FROM diarizations WHERE meeting_id=:meeting"
                ),
                {"meeting": meeting_id},
            )
            .scalars()
            .all()
        )
        compatibility_id = None
        for number in sorted(numbers):
            revision_id = str(uuid.uuid4())
            connection.execute(
                sa.text(
                    "INSERT INTO processing_revisions (id, recording_id, revision, created_at) "
                    "VALUES (:id, :recording, :revision, :created)"
                ),
                {"id": revision_id, "recording": recording_id, "revision": number, "created": datetime.now(UTC)},
            )
            if number == 1:
                compatibility_id = revision_id
            connection.execute(
                sa.text(
                    "UPDATE diarizations SET processing_revision_id=:id "
                    "WHERE meeting_id=:meeting AND processing_revision=:revision"
                ),
                {"id": revision_id, "meeting": meeting_id, "revision": number},
            )
            if number == 1:
                connection.execute(
                    sa.text("UPDATE transcripts SET processing_revision_id=:id WHERE meeting_id=:meeting"),
                    {"id": revision_id, "meeting": meeting_id},
                )
        connection.execute(
            sa.text(
                "INSERT INTO recording_processing_states (recording_id, legacy_compatibility_revision_id) "
                "VALUES (:recording, :legacy)"
            ),
            {"recording": recording_id, "legacy": compatibility_id},
        )

    op.drop_constraint("uq_transcript_meeting_id", "transcripts", type_="unique")
    op.create_unique_constraint(
        "uq_transcript_meeting_revision", "transcripts", ["meeting_id", "processing_revision_id"]
    )
    op.create_unique_constraint(
        "uq_diarization_meeting_revision_id", "diarizations", ["meeting_id", "processing_revision_id"]
    )
    # Older workers may still insert unversioned rows during the T-15 handoff;
    # nullable revision IDs must not defeat the former meeting-only uniqueness.
    op.create_index(
        "uq_transcript_unversioned_meeting",
        "transcripts",
        ["meeting_id"],
        unique=True,
        postgresql_where=sa.text("processing_revision_id IS NULL"),
    )


def downgrade() -> None:
    # The old transcript uniqueness cannot represent two revisions. Refuse to
    # silently discard user data when reversing a deployed migration.
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text("SELECT 1 FROM transcripts GROUP BY meeting_id HAVING count(*) > 1 LIMIT 1")
    ).first()
    if duplicates:
        raise RuntimeError("cannot downgrade processing revisions with multiple transcripts per meeting")
    op.drop_index("uq_transcript_unversioned_meeting", table_name="transcripts")
    op.drop_constraint("uq_diarization_meeting_revision_id", "diarizations", type_="unique")
    op.drop_constraint("uq_transcript_meeting_revision", "transcripts", type_="unique")
    op.create_unique_constraint("uq_transcript_meeting_id", "transcripts", ["meeting_id"])
    op.drop_constraint("fk_diarization_processing_revision", "diarizations", type_="foreignkey")
    op.drop_constraint("fk_transcript_processing_revision", "transcripts", type_="foreignkey")
    op.drop_column("diarizations", "processing_revision_id")
    op.drop_column("transcripts", "processing_revision_id")
    op.drop_table("processing_revision_outbox")
    op.drop_table("recording_processing_states")
    op.drop_table("processing_revisions")
