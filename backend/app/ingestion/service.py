"""Ingestion service — processes the delivery of a SessionRecording from any origin.

The pipeline is identical regardless of whether `capture_origin` is
"chrome_extension" or "server_bot". The field is stored for traceability
but doesn't alter the flow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting, RecordingMediaSource, RecordingNotice, SessionRecording
from app.ingestion.schemas import IngestionData


async def process_ingestion(
    session: AsyncSession,
    data: IngestionData,
    audio_ref: str,
    video_ref: str | None,
    created_by: str,
) -> tuple[SessionRecording, bool]:
    """Processes an ingestion from any capture source.

    1. Checks idempotency: if the key already exists, returns the existing recording.
    2. If the Meeting doesn't exist, creates it automatically (MVP workaround) with
       created_by = id of the authenticated user who uploaded it.
    3. Creates the SessionRecording with capture_origin (does NOT alter the pipeline).
    4. Records a RecordingNotice if notice_issued_at is present.
    5. Returns the tuple (SessionRecording, is_new).
    """
    # 1. Idempotency — if the key already exists, return the existing recording.
    stmt = select(SessionRecording).where(
        SessionRecording.idempotency_key == data.idempotency_key
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    # 2. Ensure Meeting exists (auto-create if not — MVP workaround for extension flow)
    now = datetime.now(UTC)
    meeting = await session.get(Meeting, data.meeting_id)
    if meeting is None:
        meeting = Meeting(
            id=data.meeting_id,
            meet_link=data.meet_link or "https://meet.google.com/unknown",
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

    await session.flush()
    await session.refresh(recording)

    # 5. Return the created recording (it's new).
    return recording, True
