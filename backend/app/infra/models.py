"""SQLAlchemy domain models for sauri — Capture and Transcription module."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database import Base

# ---------------------------------------------------------------------------
# Meeting
# ---------------------------------------------------------------------------


class Meeting(Base):
    """Record of a Google Meet meeting managed by sauri (Req. 1, 4)."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meet_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    origin: Mapped[str] = mapped_column(String(64), nullable=False)  # link | calendar_invite | manual
    calendar_invite_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    scheduled_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    process_state: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # queued | joining | recording | transcribing | completed | failed
    failure_cause: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # could_not_join | meeting_cancelled | engine_failure
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# StateHistory
# ---------------------------------------------------------------------------


class StateHistory(Base):
    """History of state transitions for a Meeting (Req. 4.2)."""

    __tablename__ = "state_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# SessionRecording
# ---------------------------------------------------------------------------


class SessionRecording(Base):
    """Audio+video recording associated 1:1 with a Meeting (Req. 2.3)."""

    __tablename__ = "session_recordings"
    __table_args__ = (
        UniqueConstraint("meeting_id", name="uq_session_recording_meeting_id"),
        UniqueConstraint("idempotency_key", name="uq_session_recording_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    capture_origin: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # chrome_extension | server_bot | web_upload
    audio_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    video_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    video_presence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )

    media_sources: Mapped[list["RecordingMediaSource"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )


class RecordingMediaSource(Base):
    """A private stored media object belonging to a session recording."""

    __tablename__ = "recording_media_sources"
    __table_args__ = (
        UniqueConstraint(
            "recording_id", "kind", "object_ref", name="uq_recording_media_source_ref"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("session_recordings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_label: Mapped[str] = mapped_column(String(64), nullable=False)

    recording: Mapped[SessionRecording] = relationship(back_populates="media_sources")


class PendingObjectDeletion(Base):
    """Durable cleanup task for a staged object not referenced by a recording."""

    __tablename__ = "pending_object_deletions"
    __table_args__ = (
        UniqueConstraint(
            "cleanup_scope_hash",
            "object_ref",
            name="uq_pending_object_deletion_scope_ref",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cleanup_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(2048), nullable=False)


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


class Transcript(Base):
    """Spanish-language transcript generated from the recording (Req. 3)."""

    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_transcript_meeting_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="es-CO")
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    supports_turns: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    turns: Mapped[list["SpeechTurn"]] = relationship(
        "SpeechTurn", back_populates="transcript", lazy="select"
    )


# ---------------------------------------------------------------------------
# SpeechTurn
# ---------------------------------------------------------------------------


class SpeechTurn(Base):
    """Timed text segment within a Transcript (Req. 3.4, 3.5)."""

    __tablename__ = "speech_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    transcript: Mapped["Transcript"] = relationship(
        "Transcript", back_populates="turns"
    )


# ---------------------------------------------------------------------------
# RecordingNotice
# ---------------------------------------------------------------------------


class RecordingNotice(Base):
    """Auditable record of the recording notice issued to participants (Req. 6.1, 6.5)."""

    __tablename__ = "recording_notices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# AccessLog
# ---------------------------------------------------------------------------


class AccessLog(Base):
    """Access audit — records allowed and denied attempts (Req. 7.4)."""

    __tablename__ = "access_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)  # "allowed" | "denied"
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Diarization
# ---------------------------------------------------------------------------


class Diarization(Base):
    """Diarization result for one processing generation associated with a Meeting."""

    __tablename__ = "diarizations"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "processing_revision", name="uq_diarization_meeting_revision"
        ),
        CheckConstraint(
            "diarization_state IN "
            "('pending', 'in_progress', 'completed', 'failed', 'not_reconstructible')",
            name="ck_diarizations_state_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id"), nullable=False
    )
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id"), nullable=False
    )
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speaker_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_legacy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    diarization_state: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # pending | in_progress | completed | failed
    failure_cause: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # engine_failure when failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    speakers: Mapped[list["Speaker"]] = relationship(
        "Speaker", back_populates="diarization", lazy="select"
    )
    assignments: Mapped[list["SpeakerAssignment"]] = relationship(
        "SpeakerAssignment", back_populates="diarization", lazy="select"
    )


# ---------------------------------------------------------------------------
# Speaker
# ---------------------------------------------------------------------------


class Speaker(Base):
    """Anonymous speaker detected by diarization (Req. 6.1, 6.2, 6.3)."""

    __tablename__ = "speakers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    diarization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diarizations.id", ondelete="CASCADE"), nullable=False
    )
    raw_label: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # "Speaker N"
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)  # consecutive from 1

    diarization: Mapped["Diarization"] = relationship(
        "Diarization", back_populates="speakers"
    )


# ---------------------------------------------------------------------------
# SpeakerAssignment
# ---------------------------------------------------------------------------


class SpeakerAssignment(Base):
    """Assignment of a SpeechTurn to a Speaker (Req. 7.1)."""

    __tablename__ = "speaker_assignments"
    __table_args__ = (
        UniqueConstraint(
            "diarization_id", "turn_id", name="uq_speaker_assignment_diarization_turn"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    diarization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diarizations.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speech_turns.id"), nullable=False
    )
    speaker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speakers.id", ondelete="CASCADE"), nullable=False
    )
    overlap_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    diarization: Mapped["Diarization"] = relationship(
        "Diarization", back_populates="assignments"
    )
    speaker: Mapped["Speaker"] = relationship("Speaker")


# ---------------------------------------------------------------------------
# SpeakerReview (recording-speaker-review T-10)
# ---------------------------------------------------------------------------


class SpeakerReview(Base):
    """Recording/revision-scoped speaker-review aggregate (Req. 3.3-3.7, 4.1-4.4).

    Status is derived from its items; the column caches the derivation so a
    single-item disposition write cannot silently disagree with item state.
    One aggregate exists per processing revision once that revision is ready.
    """

    __tablename__ = "speaker_reviews"
    __table_args__ = (
        UniqueConstraint("meeting_id", "processing_revision", name="uq_speaker_review_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    # Processing revision this aggregate belongs to; 1 for legacy recordings.
    processing_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Derived only: "pending" | "complete" (see app.meetings.speaker_review_state).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list["SpeakerReviewItem"]] = relationship(
        "SpeakerReviewItem", back_populates="review", lazy="select"
    )


# ---------------------------------------------------------------------------
# SpeakerReviewItem
# ---------------------------------------------------------------------------


class SpeakerReviewItem(Base):
    """One immutable speaker key with an optional explicit disposition (Req. 3.3-3.7, 4.1-4.4).

    ``speaker_key`` is the immutable identifier of the initial diarization
    speaker within the review. ``disposition`` stays NULL until an explicit
    named/corrected/confirmed decision is recorded; ``version`` supports
    concurrent-write detection (T-11/T-12). The encrypted excerpt reference
    binds playback to this item's recording revision and speaker.
    """

    __tablename__ = "speaker_review_items"
    __table_args__ = (
        UniqueConstraint("review_id", "speaker_key", name="uq_speaker_review_item_speaker"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speaker_reviews.id", ondelete="CASCADE"), nullable=False
    )
    speaker_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_label: Mapped[str] = mapped_column(String(64), nullable=False)
    excerpt_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # NULL while undisposed; otherwise one of named | corrected | confirmed.
    disposition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    chosen_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # attributed | uncertain — how the speaker is currently rendered.
    attribution_state: Mapped[str] = mapped_column(String(16), nullable=False, default="uncertain")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    review: Mapped["SpeakerReview"] = relationship("SpeakerReview", back_populates="items")


class SpeakerReviewIdempotencyReceipt(Base):
    """Persist the original response for one idempotent review write."""

    __tablename__ = "speaker_review_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint("review_id", "idempotency_key", name="uq_review_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speaker_reviews.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speaker_review_items.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(Base):
    """Minimal store of authorized sauri sales users (Req. 13.1, 13.2).

    This is NOT an integration with Summan's IdP: it is a minimal,
    deterministically seeded store backing the Authentication_Service
    (`POST /api/v1/auth/login`) until an IdP integration exists.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_sales: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
