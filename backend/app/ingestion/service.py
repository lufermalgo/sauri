"""Ingestion service — processes the delivery of a SessionRecording from any origin.

The pipeline is identical regardless of whether `capture_origin` is
"chrome_extension", "server_bot", or "web_upload". The field is stored for traceability
but doesn't alter the flow.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting, RecordingMediaSource, RecordingNotice, SessionRecording
from app.ingestion.schemas import IngestionData
from app.meetings.processing_revision_service import ProcessingRevisionService


async def _find_recording_by_key(session: AsyncSession, idempotency_key: str) -> SessionRecording | None:
    result = await session.execute(select(SessionRecording).where(SessionRecording.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()


async def _classify_existing_recording(
    session: AsyncSession,
    recording: SessionRecording,
    meeting: Meeting | None,
    meeting_id: str,
    created_by: str,
) -> SessionRecording:
    existing_meeting = (
        meeting if recording.meeting_id == meeting_id else await session.get(Meeting, recording.meeting_id)
    )
    if existing_meeting is None or existing_meeting.created_by != created_by:
        raise HTTPException(status_code=404, detail="Recording not found")
    if recording.meeting_id != meeting_id:
        raise HTTPException(status_code=409, detail="Idempotency key conflict")
    return recording


async def preflight_ingestion(session: AsyncSession, data: IngestionData, created_by: str) -> SessionRecording | None:
    """Check ownership and classify a retry before any media object is written."""
    meeting = await session.get(Meeting, data.meeting_id)
    if meeting is not None and meeting.created_by != created_by:
        raise HTTPException(status_code=404, detail="Meeting not found")
    recording = await _find_recording_by_key(session, data.idempotency_key)
    if recording is None:
        return None
    return await _classify_existing_recording(session, recording, meeting, data.meeting_id, created_by)


def resolve_upload_title(title: str | None, filename: str | None) -> str:
    """Use an explicit title or a bounded filename basename for uploaded meetings."""
    if title is not None and title.strip():
        return title

    basename = (filename or "").replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    return (basename or "Untitled recording")[:512]


async def process_ingestion(
    session: AsyncSession,
    data: IngestionData,
    audio_ref: str,
    video_ref: str | None,
    created_by: str,
    request_fingerprint: str | None = None,
) -> tuple[SessionRecording, bool]:
    """Processes an ingestion from any capture source.

    1. Checks idempotency: if the key already exists, returns the existing recording.
    2. If the Meeting doesn't exist, creates it automatically (MVP workaround) with
       created_by = id of the authenticated user who uploaded it.
    3. Creates the SessionRecording with capture_origin (does NOT alter the pipeline).
    4. Records a RecordingNotice if notice_issued_at is present.
    5. Returns the tuple (SessionRecording, is_new).
    """
    # 1. Repeat ownership and idempotency checks after media storage to cover races.
    existing = await preflight_ingestion(session, data, created_by)
    if existing is not None:
        if request_fingerprint is not None:
            await ProcessingRevisionService(session).admit_candidate(
                owner_id=created_by,
                recording_id=existing.id,
                request_id=data.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        return existing, False

    # 2. Ensure Meeting exists (auto-create upload-only meetings without a Meet link).
    now = datetime.now(UTC)
    meeting = await session.get(Meeting, data.meeting_id)
    if meeting is None:
        meeting = Meeting(
            id=data.meeting_id,
            meet_link=data.meet_link,
            title=data.title,
            origin="manual",
            process_state="recording",
            created_by=created_by,
            created_at=now,
        )
        session.add(meeting)
        await session.flush()

    # 3. Create SessionRecording
    recording = SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=data.meeting_id,
        idempotency_key=data.idempotency_key,
        capture_origin=data.capture_origin,
        audio_ref=audio_ref,
        video_ref=video_ref,
        video_presence=data.video_presence,
        duration_seconds=data.duration_seconds,
        interrupted=data.interrupted,
        finished_at=now,
    )
    session.add(recording)
    session.add(
        RecordingMediaSource(
            id=str(uuid.uuid4()),
            recording_id=recording.id,
            kind="audio",
            object_ref=audio_ref,
            quality_label="Original",
        )
    )
    if video_ref is not None:
        session.add(
            RecordingMediaSource(
                id=str(uuid.uuid4()),
                recording_id=recording.id,
                kind="video",
                object_ref=video_ref,
                video_offset_ms=data.video_offset_ms,
                quality_label="Original",
            )
        )

    # 4. Record a RecordingNotice if the timestamp was provided.
    if data.notice_issued_at is not None:
        notice = RecordingNotice(
            id=str(uuid.uuid4()),
            meeting_id=data.meeting_id,
            issued_at=datetime.fromisoformat(data.notice_issued_at),
        )
        session.add(notice)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await _find_recording_by_key(session, data.idempotency_key)
        if existing is None:
            raise
        meeting = await session.get(Meeting, data.meeting_id)
        existing = await _classify_existing_recording(session, existing, meeting, data.meeting_id, created_by)
        return existing, False

    await session.refresh(recording)
    # Admission and its outbox event share the caller's upload transaction. The
    # dispatcher/finalizer belong to T-15; neither is faked by the upload path.
    await ProcessingRevisionService(session).admit_candidate(
        owner_id=created_by,
        recording_id=recording.id,
        request_id=data.idempotency_key,
        request_fingerprint=request_fingerprint or ("sha256:" + hashlib.sha256(audio_ref.encode()).hexdigest()),
    )

    # 5. Return the created recording (it's new).
    return recording, True
