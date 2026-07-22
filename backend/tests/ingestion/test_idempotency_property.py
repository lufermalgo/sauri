"""Property test for ingestion idempotency by idempotency_key (service.py).

# Feature: meeting-capture-transcription, Property 14: Idempotency of pipeline and ingestion handlers
Task: 9.3 — Validates: Requirements 2.3, 4.1, 4.2

Task 9.4 (unit test): RecordingNotice recording.
Validates: Requirements 6.5
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import RecordingNotice, SessionRecording
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion


def _ingestion_data(meeting_id: str, key: str, notice: str | None = None) -> IngestionData:
    return IngestionData(
        meeting_id=meeting_id,
        idempotency_key=key,
        capture_origin="chrome_extension",
        duration_seconds=60,
        interrupted=False,
        notice_issued_at=notice,
    )


# ---------------------------------------------------------------------------
# Property 14 (ingestion facet): Ingestion idempotency
# Feature: meeting-capture-transcription, Property 14: Idempotency of pipeline and ingestion handlers
# Validates: Requirements 2.3, 4.1, 4.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_retries=st.integers(min_value=1, max_value=6))
@pytest.mark.asyncio
async def test_property_14_retries_same_key_do_not_duplicate_recording(
    db_session: AsyncSession, n_retries: int
) -> None:
    """Retrying ingestion with the same idempotency_key creates at most one SessionRecording."""
    meeting_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    data = _ingestion_data(meeting_id, key)

    results = []
    for i in range(n_retries):
        recording, is_new = await process_ingestion(
            db_session, data, audio_ref=f"audio/{i}.webm", video_ref=None, created_by="test-user"
        )
        await db_session.commit()
        results.append((recording, is_new))

    # Only the first attempt should be "new"
    assert results[0][1] is True
    assert all(is_new is False for _, is_new in results[1:])

    # All calls return the same SessionRecording (same id)
    ids = {recording.id for recording, _ in results}
    assert len(ids) == 1

    result = await db_session.execute(
        select(SessionRecording).where(SessionRecording.idempotency_key == key)
    )
    assert len(result.scalars().all()) == 1


# ---------------------------------------------------------------------------
# Task 9.4: auditable RecordingNotice record
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_ingestion_records_recording_notice(
    db_session: AsyncSession,
) -> None:
    """Ingestion persists the auditable consent record when the timestamp is provided."""
    meeting_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    issued_at = datetime.now(UTC).isoformat()
    data = _ingestion_data(meeting_id, key, notice=issued_at)

    await process_ingestion(db_session, data, audio_ref="audio/x.webm", video_ref=None, created_by="test-user")
    await db_session.commit()

    result = await db_session.execute(
        select(RecordingNotice).where(RecordingNotice.meeting_id == meeting_id)
    )
    notices = result.scalars().all()
    assert len(notices) == 1


@pytest.mark.asyncio
async def test_example_ingestion_without_timestamp_records_no_notice(
    db_session: AsyncSession,
) -> None:
    """Without notice_issued_at, no RecordingNotice record is created."""
    meeting_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    data = _ingestion_data(meeting_id, key, notice=None)

    await process_ingestion(db_session, data, audio_ref="audio/x.webm", video_ref=None, created_by="test-user")
    await db_session.commit()

    result = await db_session.execute(
        select(RecordingNotice).where(RecordingNotice.meeting_id == meeting_id)
    )
    assert result.scalars().all() == []
