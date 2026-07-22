"""Tests for DiarizationRepository (repository.py).

# Feature: identificacion-hablantes
Tasks: 11.1, 11.2, 11.3, 11.4, 11.5
Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.5, 10.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    Transcript,
    SpeechTurn,
)
from app.diarization.repository import DiarizationRepository


# ---------------------------------------------------------------------------
# Helpers — build the real entity graph (no mocks)
# ---------------------------------------------------------------------------


def _create_meeting(meeting_id: str) -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="completed",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(timezone.utc),
    )


def _create_transcript(meeting_id: str) -> Transcript:
    return Transcript(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        language="es-CO",
        provider="local",
        supports_turns=True,
        expires_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _create_turns(transcript_id: str, n: int) -> list[SpeechTurn]:
    return [
        SpeechTurn(
            id=str(uuid.uuid4()),
            transcript_id=transcript_id,
            text=f"Texto turno {i+1}",
            start_ms=i * 1000,
            end_ms=(i + 1) * 1000,
            sequence=i + 1,
        )
        for i in range(n)
    ]


def _create_diarization(
    meeting_id: str, transcript_id: str, speaker_count: int, provider: str = "diar-engine-local"
) -> Diarization:
    return Diarization(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        transcript_id=transcript_id,
        provider=provider,
        speaker_count=speaker_count,
        diarization_state="completed",
        failure_cause=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _create_speakers(diarization_id: str, n: int) -> list[Speaker]:
    return [
        Speaker(
            id=str(uuid.uuid4()),
            diarization_id=diarization_id,
            raw_label=f"SPEAKER_{i:02d}",
            label=f"Speaker {i+1}",
            sequence=i + 1,
        )
        for i in range(n)
    ]


def _create_assignments(
    diarization_id: str, turns: list[SpeechTurn], speakers: list[Speaker]
) -> list[SpeakerAssignment]:
    assignments = []
    for i, turn in enumerate(turns):
        speaker = speakers[i % len(speakers)]
        assignments.append(
            SpeakerAssignment(
                id=str(uuid.uuid4()),
                diarization_id=diarization_id,
                turn_id=turn.id,
                speaker_id=speaker.id,
            )
        )
    return assignments


# ---------------------------------------------------------------------------
# Property 12: Uniqueness of the Diarization per Meeting (Task 11.1)
# Feature: identificacion-hablantes, Property 12: Uniqueness of the Diarization per Meeting
# Validates: Requirements 8.1, 10.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(attempts=st.integers(min_value=2, max_value=5))
@pytest.mark.asyncio
async def test_property_12_diarization_uniqueness_per_meeting(
    session_factory: async_sessionmaker, attempts: int
):
    """Multiple attempts to persist a Diarization for the same meeting_id don't
    produce more than one Diarization (UniqueConstraint uq_diarization_meeting_id)."""
    meeting_id = str(uuid.uuid4())
    repo = DiarizationRepository(session_factory)

    # Create the base meeting and transcript
    async with session_factory() as session:
        async with session.begin():
            session.add(_create_meeting(meeting_id))
            transcript = _create_transcript(meeting_id)
            session.add(transcript)
            transcript_id = transcript.id

    # First processing: succeeds
    async with session_factory() as session:
        async with session.begin():
            diar = _create_diarization(meeting_id, transcript_id, speaker_count=2)
            await repo.create(session, diar, [], [])

    # Additional attempts for the same meeting_id must fail due to the constraint
    for _ in range(attempts - 1):
        with pytest.raises(Exception):
            async with session_factory() as session:
                async with session.begin():
                    dup_diar = _create_diarization(meeting_id, transcript_id, speaker_count=3)
                    await repo.create(session, dup_diar, [], [])

    # There should only be one Diarization for the meeting_id
    async with session_factory() as session:
        result = await session.execute(
            select(Diarization).where(Diarization.meeting_id == meeting_id)
        )
        diarizations = result.scalars().all()
    assert len(diarizations) == 1


# ---------------------------------------------------------------------------
# Property 13: Persistence atomicity (Task 11.2)
# Feature: identificacion-hablantes, Property 13: Persistence atomicity
# Validates: Requirements 8.2, 8.3, 10.6
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(speaker_count=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_13_persistence_atomicity(
    session_factory: async_sessionmaker, speaker_count: int
):
    """A failure midway through a write rolls back the whole transaction: no
    partial records remain (Diarization, Speakers, or Assignments)."""
    meeting_id = str(uuid.uuid4())
    repo = DiarizationRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_create_meeting(meeting_id))
            transcript = _create_transcript(meeting_id)
            session.add(transcript)
            transcript_id = transcript.id

    # Inject a failure: two Speakers with the same PK violates uniqueness (PK),
    # a constraint SQLite and PostgreSQL both enforce -> forces a rollback.
    with pytest.raises(Exception):
        async with session_factory() as session:
            async with session.begin():
                diar = _create_diarization(meeting_id, transcript_id, speaker_count)
                speakers = _create_speakers(diar.id, speaker_count)
                duplicate_pk = speakers[0].id
                colliding_speaker = Speaker(
                    id=duplicate_pk,  # Duplicate PK -> IntegrityError on flush
                    diarization_id=diar.id,
                    raw_label="SPEAKER_DUP",
                    label="Speaker dup",
                    sequence=999,
                )
                await repo.create(session, diar, speakers + [colliding_speaker], [])

    # Full rollback: there should be no Diarization, Speakers, or Assignments
    async with session_factory() as session:
        diar_count = (
            await session.execute(
                select(Diarization).where(Diarization.meeting_id == meeting_id)
            )
        ).scalars().all()
        speaker_count_result = (await session.execute(select(Speaker))).scalars().all()
        assignment_count = (
            await session.execute(select(SpeakerAssignment))
        ).scalars().all()

    assert len(diar_count) == 0
    assert len(speaker_count_result) == 0
    assert len(assignment_count) == 0


# ---------------------------------------------------------------------------
# Property 14: Provider metadata recording (Task 11.3)
# Feature: identificacion-hablantes, Property 14: Provider metadata recording
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    speaker_count=st.integers(min_value=0, max_value=8),
    provider=st.sampled_from(["diar-engine-local", "diarization-cloud"]),
)
@pytest.mark.asyncio
async def test_property_14_provider_metadata_recording(
    session_factory: async_sessionmaker, speaker_count: int, provider: str
):
    """The Diarization persists consistent provider and speaker_count."""
    meeting_id = str(uuid.uuid4())
    repo = DiarizationRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_create_meeting(meeting_id))
            transcript = _create_transcript(meeting_id)
            session.add(transcript)
            transcript_id = transcript.id

    async with session_factory() as session:
        async with session.begin():
            diar = _create_diarization(meeting_id, transcript_id, speaker_count, provider)
            speakers = _create_speakers(diar.id, speaker_count)
            await repo.create(session, diar, speakers, [])

    retrieved = await repo.get_by_meeting(meeting_id)
    assert retrieved is not None
    assert retrieved.provider == provider
    assert retrieved.speaker_count == speaker_count
    assert len(retrieved.speakers) == speaker_count


# ---------------------------------------------------------------------------
# Property 15: Persistence and retrieval round-trip (Task 11.4)
# Feature: identificacion-hablantes, Property 15: Persistence and retrieval round-trip
# Validates: Requirements 8.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    speaker_count=st.integers(min_value=1, max_value=5),
    num_turns=st.integers(min_value=1, max_value=10),
)
@pytest.mark.asyncio
async def test_property_15_persistence_retrieval_roundtrip(
    session_factory: async_sessionmaker, speaker_count: int, num_turns: int
):
    """Persisting Diarization + Speakers + Assignments and retrieving with
    get_by_meeting returns everything equivalent (selectinload)."""
    meeting_id = str(uuid.uuid4())
    repo = DiarizationRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_create_meeting(meeting_id))
            transcript = _create_transcript(meeting_id)
            session.add(transcript)
            transcript_id = transcript.id
            turns = _create_turns(transcript_id, num_turns)
            for turn in turns:
                session.add(turn)

    async with session_factory() as session:
        async with session.begin():
            diar = _create_diarization(meeting_id, transcript_id, speaker_count)
            speakers = _create_speakers(diar.id, speaker_count)
            assignments = _create_assignments(diar.id, turns, speakers)
            await repo.create(session, diar, speakers, assignments)

    retrieved = await repo.get_by_meeting(meeting_id)
    assert retrieved is not None
    assert retrieved.meeting_id == meeting_id
    assert retrieved.transcript_id == transcript_id
    assert retrieved.diarization_state == "completed"
    assert len(retrieved.speakers) == speaker_count
    assert len(retrieved.assignments) == num_turns

    sequences = sorted(sp.sequence for sp in retrieved.speakers)
    assert sequences == list(range(1, speaker_count + 1))


# ---------------------------------------------------------------------------
# Example test — lookup without a Diarization (Task 11.5)
# Validates: Requirements 8.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_get_by_meeting_without_diarization(
    session_factory: async_sessionmaker,
):
    """get_by_meeting returns None if no Diarization exists (no error)."""
    repo = DiarizationRepository(session_factory)
    result = await repo.get_by_meeting("inexistente-id")
    assert result is None
