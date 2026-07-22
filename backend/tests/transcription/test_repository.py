"""Tests for TranscriptRepository (repository.py).

# Feature: transcripcion-asr
Tasks: 7.3, 7.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import given, HealthCheck, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SpeechTurn, Transcript
from app.transcription.repository import TranscriptRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_meeting(meeting_id: str) -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="transcribing",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(timezone.utc),
    )


def _create_transcript(meeting_id: str) -> tuple[Transcript, str]:
    t_id = str(uuid.uuid4())
    return Transcript(
        id=t_id,
        meeting_id=meeting_id,
        language="es-CO",
        provider="local",
        supports_turns=True,
        expires_at=None,
        created_at=datetime.now(timezone.utc),
    ), t_id


def _create_turns(transcript_id: str, n: int) -> list[SpeechTurn]:
    turns = []
    for i in range(n):
        turns.append(
            SpeechTurn(
                id=str(uuid.uuid4()),
                transcript_id=transcript_id,
                text=f"Texto segmento {i+1}",
                start_ms=i * 1000,
                end_ms=(i + 1) * 1000,
                sequence=i + 1,
            )
        )
    return turns


# ---------------------------------------------------------------------------
# Property 13: Persistence and retrieval round-trip (Task 7.3)
# Feature: transcripcion-asr, Property 13: Persistence round-trip
# Validates: Requirements 7.7
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_turns=st.integers(min_value=1, max_value=10))
@pytest.mark.asyncio
async def test_property_13_persistence_roundtrip(
    session_factory: async_sessionmaker, num_turns: int
):
    """Creating and retrieving a Transcript with N turns preserves all data."""
    meeting_id = str(uuid.uuid4())
    repo = TranscriptRepository(session_factory)

    # Persist
    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting(meeting_id)
            session.add(meeting)

            transcript, t_id = _create_transcript(meeting_id)
            turns = _create_turns(t_id, num_turns)
            await repo.create(session, transcript, turns)

    # Retrieve
    result = await repo.get_by_meeting(meeting_id)

    assert result is not None
    assert result.meeting_id == meeting_id
    assert result.language == "es-CO"
    assert result.provider == "local"
    assert result.supports_turns is True
    assert len(result.turns) == num_turns

    for i, turn in enumerate(sorted(result.turns, key=lambda t: t.sequence)):
        assert turn.sequence == i + 1
        assert turn.start_ms == i * 1000
        assert turn.end_ms == (i + 1) * 1000


# ---------------------------------------------------------------------------
# Example test — lookup without a transcript (Task 7.4)
# Validates: Requirements 7.8
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_get_by_meeting_without_transcript(
    session_factory: async_sessionmaker,
):
    """get_by_meeting returns None if no transcript exists (no error)."""
    repo = TranscriptRepository(session_factory)
    result = await repo.get_by_meeting("inexistente-id")
    assert result is None
