"""SQLAlchemy domain models for sauri — Capture and Transcription module."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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
        CheckConstraint(
            "thumbnail_state IS NULL OR thumbnail_state IN ('ready', 'audio_only', 'unavailable')",
            name="ck_session_recordings_thumbnail_state",
        ),
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
    # Preview frame for the library: NULL state = not attempted yet.
    thumbnail_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_state: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ready | audio_only | unavailable

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
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="es", server_default="es")
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
# TranscriptWord
# ---------------------------------------------------------------------------


class TranscriptWord(Base):
    """Word with engine timestamps within a Transcript, in transcript order."""

    __tablename__ = "transcript_words"
    __table_args__ = (
        UniqueConstraint("transcript_id", "sequence", name="uq_transcript_word_sequence"),
        Index("ix_transcript_words_transcript_start", "transcript_id", "start_ms"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    timing_repaired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
# WordSpeakerAssignment
# ---------------------------------------------------------------------------


class WordSpeakerAssignment(Base):
    """Speaker attribution of one TranscriptWord within one Diarization."""

    __tablename__ = "word_speaker_assignments"
    __table_args__ = (
        CheckConstraint(
            "state IN ('assigned', 'ambiguous', 'unassigned')",
            name="ck_word_speaker_assignments_state_valid",
        ),
    )

    diarization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diarizations.id", ondelete="CASCADE"), primary_key=True
    )
    word_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcript_words.id", ondelete="CASCADE"), primary_key=True
    )
    speaker_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("speakers.id", ondelete="CASCADE"), nullable=True
    )  # NULL when unassigned
    state: Mapped[str] = mapped_column(String(16), nullable=False)  # assigned | ambiguous | unassigned
    candidates_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON, nullable=True
    )  # only when ambiguous


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
# Manual meeting recovery persistence
# ---------------------------------------------------------------------------


class MeetingProcessingClaim(Base):
    """Durable per-meeting processing generation and exclusive claim identity."""

    __tablename__ = "meeting_processing_claims"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_processing_claim_meeting_id"),)

    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MeetingRecoveryOperation(Base):
    """Content-free audit and idempotency record for one recovery operation."""

    __tablename__ = "meeting_recovery_operations"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "meeting_id", "idempotency_key",
            name="uq_recovery_operation_idempotency_scope",
        ),
        CheckConstraint(
            "preservation_counts IS NULL OR "
            "CAST(preservation_counts AS TEXT) = '{}'",
            name="ck_recovery_operation_empty_preservation_counts",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    # Store a digest of the caller's key, never the request's raw value.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preservation_snapshot_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    preservation_counts: Mapped[dict[str, int] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MeetingRecoveryOutbox(Base):
    """Durable outbox envelope containing opaque job identifiers only."""

    __tablename__ = "meeting_recovery_outbox"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_recovery_outbox_operation_id"),
        CheckConstraint(
            "CAST(job_identifiers AS TEXT) = '{}'",
            name="ck_recovery_outbox_empty_job_identifiers",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meeting_recovery_operations.id"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    job_identifiers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    processing_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ManualRecoveryPilotGate(Base):
    """Singleton persistence for the separately authorized recovery pilot."""

    __tablename__ = "manual_recovery_pilot_gate"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_manual_recovery_pilot_gate_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="disabled")
    allowed_meeting_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True
    )
    authorized_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pilot_operation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("meeting_recovery_operations.id"),
        unique=True, nullable=True,
    )
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_artifact_snapshot_match: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )


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
    default_summary_template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("summary_templates.id", ondelete="SET NULL", use_alter=True,
                               name="fk_users_default_summary_template_id_summary_templates"), nullable=True
    )


# ---------------------------------------------------------------------------
# Summary templates and generated summaries
# ---------------------------------------------------------------------------


class TemplateCategory(Base):
    """Optional grouping for a user's summary templates (R4)."""

    __tablename__ = "template_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SummaryTemplate(Base):
    """User-owned editable template with opaque instructions (R3/R4)."""

    __tablename__ = "summary_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("template_categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SummaryRequestOutbox(Base):
    """Durable request and immutable selected-template snapshot (D4/D15)."""

    __tablename__ = "summary_request_outbox"
    __table_args__ = (
        UniqueConstraint("transcript_id", "generation", name="uq_summary_request_transcript_generation"),
        CheckConstraint(
            "(template_id IS NOT NULL AND template_version IS NOT NULL AND instructions_snapshot IS NOT NULL) OR "
            "(status = 'failed' AND template_id IS NULL AND template_version IS NULL "
            "AND instructions_snapshot IS NULL)",
            name="ck_summary_request_snapshot_or_failed",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("summary_templates.id"), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    failure_cause: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lifecycle timestamps: accepted by the API, taken by the worker (first attempt), settled.
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedSummaryEvent(Base):
    """Transactional idempotency ledger for successfully processed events."""

    __tablename__ = "processed_summary_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeetingSummary(Base):
    """Structured summary for one request generation on a transcript (R1/R6)."""

    __tablename__ = "meeting_summaries"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_meeting_summary_event_id"),
        UniqueConstraint("transcript_id", "generation", name="uq_meeting_summary_transcript_generation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("summary_templates.id"), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    key_points_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Explicit stage regeneration (#1053)
# ---------------------------------------------------------------------------


class RegenerationOperation(Base):
    """One explicit, user-requested re-run of a pipeline stage and its audit trail.

    The only way a completed stage is computed again. A meeting has at most one
    active (accepted or running) operation; the partial unique index backs the
    meeting row lock that the endpoint takes.
    """

    __tablename__ = "regeneration_operations"
    __table_args__ = (
        UniqueConstraint(
            "requested_by", "meeting_id", "idempotency_key", name="uq_regeneration_idempotency_scope"
        ),
        CheckConstraint(
            "stage IN ('transcription', 'speakers', 'summary')", name="ck_regeneration_stage_valid"
        ),
        CheckConstraint(
            "status IN ('accepted', 'running', 'succeeded', 'failed')", name="ck_regeneration_status_valid"
        ),
        Index(
            "uq_regeneration_one_active_per_meeting",
            "meeting_id",
            unique=True,
            postgresql_where=text("status IN ('accepted', 'running')"),
            sqlite_where=text("status IN ('accepted', 'running')"),
        ),
        Index("ix_regeneration_operations_meeting_requested", "meeting_id", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # Digest of the caller's Idempotency-Key header; NULL when none was sent.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cascade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Template for a summary run, or for the summary that ends a cascade.
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("summary_templates.id", ondelete="SET NULL"), nullable=True
    )
    parent_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processing_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diarization_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Content-free outcome details, e.g. how many speaker names were carried over.
    details: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
