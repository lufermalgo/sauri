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
        video_presence="absent",
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
    assert {recording.audio_ref for recording, _ in results} == {"audio/0.webm"}

    result = await db_session.execute(
        select(SessionRecording).where(SessionRecording.idempotency_key == key)
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_same_owner_retry_for_existing_meeting_returns_original_recording(
    db_session: AsyncSession,
) -> None:
    """A same-owner retry for an already owned meeting keeps the original recording."""
    from app.infra.models import Meeting

    owner_id = "synthetic-meeting-owner"
    meeting_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    db_session.add(
        Meeting(
            id=meeting_id,
            meet_link=None,
            title="Synthetic owned meeting",
            origin="manual",
            process_state="recording",
            created_by=owner_id,
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    data = _ingestion_data(meeting_id, key)
    original, is_new = await process_ingestion(
        db_session,
        data,
        audio_ref="private/original-audio",
        video_ref=None,
        created_by=owner_id,
    )
    await db_session.commit()

    retry, retry_is_new = await process_ingestion(
        db_session,
        data,
        audio_ref="private/retry-audio",
        video_ref=None,
        created_by=owner_id,
    )
    await db_session.commit()

    assert is_new is True
    assert retry_is_new is False
    assert retry.id == original.id
    assert retry.meeting_id == meeting_id
    assert retry.audio_ref == "private/original-audio"
    persisted_meeting = await db_session.get(Meeting, meeting_id)
    assert persisted_meeting is not None
    assert persisted_meeting.created_by == owner_id
    recordings = (await db_session.execute(select(SessionRecording))).scalars().all()
    assert [recording.id for recording in recordings] == [original.id]


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


@pytest.mark.asyncio
async def test_ingestion_rejects_a_meeting_owned_by_another_user_without_persisting_media(
    db_session: AsyncSession,
) -> None:
    """Foreign meetings look absent and receive neither recording nor media refs."""
    from fastapi import HTTPException

    from app.infra.models import Meeting, RecordingMediaSource

    meeting_id = str(uuid.uuid4())
    foreign_meeting = Meeting(
        id=meeting_id,
        meet_link=None,
        title="Synthetic private meeting",
        origin="manual",
        process_state="recording",
        created_by="foreign-owner",
        created_at=datetime.now(UTC),
    )
    db_session.add(foreign_meeting)
    await db_session.commit()

    with pytest.raises(HTTPException) as error:
        await process_ingestion(
            db_session,
            _ingestion_data(meeting_id, "foreign-meeting-key"),
            audio_ref="private/synthetic-audio",
            video_ref=None,
            created_by="requesting-owner",
        )

    assert error.value.status_code == 404
    assert error.value.detail == "not_found"
    assert foreign_meeting.process_state == "recording"
    assert (await db_session.execute(select(SessionRecording))).scalars().all() == []
    assert (await db_session.execute(select(RecordingMediaSource))).scalars().all() == []


@pytest.mark.asyncio
async def test_idempotency_key_owned_by_another_user_is_not_disclosed(
    db_session: AsyncSession,
) -> None:
    """A foreign owner's retry cannot learn their recording ID, state, or media refs."""
    from fastapi import HTTPException

    from app.infra.models import Meeting, RecordingMediaSource

    meeting_id = str(uuid.uuid4())
    recording_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    db_session.add(
        Meeting(
            id=meeting_id,
            meet_link=None,
            title=None,
            origin="manual",
            process_state="completed",
            created_by="foreign-owner",
            created_at=now,
        )
    )
    db_session.add(
        SessionRecording(
            id=recording_id,
            meeting_id=meeting_id,
            idempotency_key="foreign-owner-key",
            capture_origin="web_upload",
            audio_ref="private/synthetic-audio",
            video_ref=None,
            duration_seconds=12,
            interrupted=False,
            finished_at=now,
        )
    )
    db_session.add(
        RecordingMediaSource(
            id=str(uuid.uuid4()),
            recording_id=recording_id,
            kind="audio",
            object_ref="private/synthetic-audio",
            quality_label="Original",
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as error:
        await process_ingestion(
            db_session,
            _ingestion_data(str(uuid.uuid4()), "foreign-owner-key"),
            audio_ref="private/attacker-upload",
            video_ref=None,
            created_by="requesting-owner",
        )

    assert error.value.status_code == 404
    assert error.value.detail == "not_found"
    assert recording_id not in str(error.value.detail)
    assert "private/" not in str(error.value.detail)
    persisted = (await db_session.execute(select(SessionRecording))).scalars().all()
    assert [recording.id for recording in persisted] == [recording_id]
    refs = (await db_session.execute(select(RecordingMediaSource))).scalars().all()
    assert [source.object_ref for source in refs] == ["private/synthetic-audio"]


@pytest.mark.asyncio
async def test_same_owner_cannot_reuse_idempotency_key_for_another_meeting(
    db_session: AsyncSession,
) -> None:
    """Cross-meeting key reuse returns a generic conflict without the existing ID."""
    from fastapi import HTTPException

    owner_id = "synthetic-owner"
    original_meeting_id = str(uuid.uuid4())
    original, _ = await process_ingestion(
        db_session,
        _ingestion_data(original_meeting_id, "owner-meeting-key"),
        audio_ref="private/original-audio",
        video_ref=None,
        created_by=owner_id,
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as error:
        await process_ingestion(
            db_session,
            _ingestion_data(str(uuid.uuid4()), "owner-meeting-key"),
            audio_ref="private/retry-audio",
            video_ref=None,
            created_by=owner_id,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "conflict"
    assert original.id not in str(error.value.detail)
    assert "private/" not in str(error.value.detail)
    assert len((await db_session.execute(select(SessionRecording))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_unique_key_race_reloads_recording_after_rollback() -> None:
    """A concurrent winner is classified from a fresh post-rollback lookup."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from sqlalchemy.exc import IntegrityError

    from app.infra.models import Meeting

    meeting_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    meeting = Meeting(
        id=meeting_id,
        meet_link=None,
        title=None,
        origin="manual",
        process_state="recording",
        created_by="synthetic-owner",
        created_at=now,
    )
    winning_recording = SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key="race-key",
        capture_origin="web_upload",
        audio_ref="private/winner-audio",
        video_ref=None,
        duration_seconds=12,
        interrupted=False,
        finished_at=now,
    )
    empty_lookup = SimpleNamespace(scalar_one_or_none=lambda: None)
    winner_lookup = SimpleNamespace(scalar_one_or_none=lambda: winning_recording)
    session = Mock()
    session.execute = AsyncMock(side_effect=[empty_lookup, winner_lookup])
    session.get = AsyncMock(return_value=meeting)
    session.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("unique constraint"))
    )
    session.rollback = AsyncMock()

    recording, is_new = await process_ingestion(
        session,
        _ingestion_data(meeting_id, "race-key"),
        audio_ref="private/loser-audio",
        video_ref=None,
        created_by="synthetic-owner",
    )

    assert is_new is False
    assert recording.id == winning_recording.id
    assert session.rollback.await_count == 1
    assert session.execute.await_count == 2
