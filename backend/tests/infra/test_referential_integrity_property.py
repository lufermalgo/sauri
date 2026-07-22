"""Property test for 1:1 referential integrity (SessionRecording / Transcript <-> Meeting).

# Feature: meeting-capture-transcription, Property 6: 1:1 referential integrity
Task: 4.2 — Validates: Requirements 2.2, 2.3, 3.3
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting, SessionRecording, Transcript


def _create_meeting(meeting_id: str) -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="recording",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


def _create_recording(meeting_id: str, key: str) -> SessionRecording:
    return SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key=key,
        capture_origin="chrome_extension",
        audio_ref=f"audio/{uuid.uuid4()}.webm",
        video_ref=None,
        duration_seconds=60,
        interrupted=False,
        finished_at=datetime.now(UTC),
    )


def _create_transcript(meeting_id: str) -> Transcript:
    return Transcript(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        language="es-CO",
        provider="local",
        supports_turns=True,
        expires_at=None,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 6: 1:1 referential integrity
# Feature: meeting-capture-transcription, Property 6: 1:1 referential integrity
# Validates: Requirements 2.2, 2.3, 3.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_attempts=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_6_a_meeting_has_at_most_one_recording(
    db_session: AsyncSession, n_attempts: int
) -> None:
    """No Meeting has more than one SessionRecording: only the first insert per meeting_id succeeds."""
    meeting_id = str(uuid.uuid4())
    db_session.add(_create_meeting(meeting_id))
    await db_session.flush()

    successes = 0
    for i in range(n_attempts):
        recording = _create_recording(meeting_id, key=f"clave-{uuid.uuid4()}-{i}")
        try:
            async with db_session.begin_nested():
                db_session.add(recording)
                await db_session.flush()
            successes += 1
        except IntegrityError:
            pass

    assert successes == 1


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_attempts=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_6_a_meeting_has_at_most_one_transcript(
    db_session: AsyncSession, n_attempts: int
) -> None:
    """Each Transcript references its Meeting and no Meeting has more than one Transcript."""
    meeting_id = str(uuid.uuid4())
    db_session.add(_create_meeting(meeting_id))
    await db_session.flush()

    successes = 0
    for _ in range(n_attempts):
        transcript = _create_transcript(meeting_id)
        try:
            async with db_session.begin_nested():
                db_session.add(transcript)
                await db_session.flush()
            successes += 1
        except IntegrityError:
            pass

    assert successes == 1


@pytest.mark.asyncio
async def test_example_recording_references_its_meeting(db_session: AsyncSession) -> None:
    """The persisted SessionRecording references exactly the Meeting it was created with."""
    meeting_id = str(uuid.uuid4())
    db_session.add(_create_meeting(meeting_id))
    recording = _create_recording(meeting_id, key=str(uuid.uuid4()))
    db_session.add(recording)
    await db_session.flush()

    assert recording.meeting_id == meeting_id
