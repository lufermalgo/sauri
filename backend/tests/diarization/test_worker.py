"""Tests for the diarization worker (worker.py).

# Feature: speaker-identification
Tasks: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
Validates: Requirements 1.3, 1.4, 1.5, 1.6, 7.4, 7.5, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1

NOTE: The mocks used here simulate ONLY the DiarizationEngine (external I/O
boundary: diar-engine / cloud service) within tests. The worker's
production code is 100% real; mocks are confined to external I/O in tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.diarization_engine import (
    DiarizationCapabilities,
    DiarizationResult,
    SpeakerSegment,
)
from app.diarization.worker import _process_diarization as _process_diarization_worker
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeechTurn,
    Transcript,
)

# ---------------------------------------------------------------------------
# Helpers — build real entities in the test DB
# ---------------------------------------------------------------------------


def _create_meeting(meeting_id: str, state: str = "completed") -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state=state,
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


def _create_recording(
    meeting_id: str, audio_ref: str = "audio/test.webm", duration_seconds: int = 120
) -> SessionRecording:
    return SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        audio_ref=audio_ref,
        video_ref=None,
        duration_seconds=duration_seconds,
        interrupted=False,
        expires_at=None,
        finished_at=datetime.now(UTC),
    )


def _create_transcript_with_turns(meeting_id: str, num_turns: int) -> tuple[Transcript, list[SpeechTurn]]:
    t_id = str(uuid.uuid4())
    transcript = Transcript(
        id=t_id,
        meeting_id=meeting_id,
        language="es-CO",
        provider="local",
        supports_turns=True,
        expires_at=None,
        created_at=datetime.now(UTC),
    )
    turns = [
        SpeechTurn(
            id=str(uuid.uuid4()),
            transcript_id=t_id,
            text=f"Turno {i+1}",
            start_ms=i * 1000,
            end_ms=(i + 1) * 1000,
            sequence=i + 1,
        )
        for i in range(num_turns)
    ]
    return transcript, turns


async def _seed_complete_meeting(
    session_factory: async_sessionmaker[AsyncSession],
    meeting_id: str,
    num_turns: int = 3,
    meeting_state: str = "completed",
) -> None:
    """Creates Meeting + SessionRecording + Transcript + SpeechTurns in the DB."""
    async with session_factory() as session, session.begin():
        session.add(_create_meeting(meeting_id, meeting_state))
        session.add(_create_recording(meeting_id))
        transcript, turns = _create_transcript_with_turns(meeting_id, num_turns)
        session.add(transcript)
        for turn in turns:
            session.add(turn)


async def _process_diarization_for_seeded_recording(
    message: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Add the persisted identity expected from the authenticated producer."""
    bound_message = dict(message)
    meeting_id = bound_message.get("meeting_id")
    if isinstance(meeting_id, str):
        async with session_factory() as session:
            meeting = await session.get(Meeting, meeting_id)
            recording = (
                await session.execute(
                    select(SessionRecording).where(
                        SessionRecording.meeting_id == meeting_id
                    )
                )
            ).scalar_one_or_none()
        if meeting is not None and recording is not None:
            bound_message.setdefault("owner_id", meeting.created_by)
            bound_message.setdefault("recording_id", recording.id)
    await _process_diarization_worker(bound_message, session_factory)


def _mock_engine(segments: list[SpeakerSegment], is_local: bool = True) -> AsyncMock:
    """Builds a mock of the DiarizationEngine (external boundary, test-only)."""
    count = len({s.raw_label for s in segments})
    engine = AsyncMock()
    engine.diarize.return_value = DiarizationResult(segments=segments, speaker_count=count)
    engine.capabilities = MagicMock(
        return_value=DiarizationCapabilities(
            is_local=is_local,
            provider_name="diar-engine-local" if is_local else "diarization-cloud",
        )
    )
    return engine


# ---------------------------------------------------------------------------
# Property 19: Invalid input / missing prerequisite (Task 13.1)
# Feature: speaker-identification, Property 19: Invalid input or missing prerequisite
# Validates: Requirements 1.3, 1.4, 1.5, 1.6
# ---------------------------------------------------------------------------

_invalid_message: st.SearchStrategy[dict[str, Any]] = st.one_of(
    st.just({}),
    st.just({"meeting_id": ""}),
    st.just({"meeting_id": "   "}),
    st.just({"meeting_id": None}),
    st.fixed_dictionaries({"meeting_id": st.integers()}),
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(message=_invalid_message)
@pytest.mark.asyncio
async def test_property_19_invalid_message_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession], message: dict[str, Any]
) -> None:
    """Missing/empty/non-string meeting_id -> finishes with no exception and nothing persisted."""
    await _process_diarization_for_seeded_recording(message, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarization))
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_property_19_nonexistent_meeting_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Nonexistent meeting_id -> ack without persisting (Req 1.5)."""
    await _process_diarization_for_seeded_recording({"meeting_id": str(uuid.uuid4())}, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarization))
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_property_19_without_transcript_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Meeting without a Transcript -> ack without persisting (Req 1.6)."""
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting(meeting_id))
        session.add(_create_recording(meeting_id))

    await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarization))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Property 11: Empty result -> valid empty Diarization (Task 13.2)
# Feature: speaker-identification, Property 11: A result with no speakers produces a valid empty Diarization
# Validates: Requirements 7.4, 7.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_11_empty_result_completed_diarization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Empty segments -> completed Diarization with 0 speakers and 0 assignments."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=3)

    engine = _mock_engine(segments=[])
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarization).where(Diarization.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()
        speakers = (await session.execute(select(Speaker))).scalars().all()

    assert diar is not None
    assert diar.diarization_state == "completed"
    assert diar.speaker_count == 0
    assert len(speakers) == 0


@pytest.mark.asyncio
async def test_property_11_without_turns_zero_assignments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Transcript without turns -> zero assignments even if there are speakers."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=0)

    segments = [
        SpeakerSegment(raw_label="SPEAKER_00", start_ms=0, end_ms=5000),
        SpeakerSegment(raw_label="SPEAKER_01", start_ms=5000, end_ms=10000),
    ]
    engine = _mock_engine(segments=segments)
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)

    from app.infra.models import SpeakerAssignment

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarization).where(Diarization.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()
        assignments = (await session.execute(select(SpeakerAssignment))).scalars().all()

    assert diar is not None
    assert diar.diarization_state == "completed"
    assert diar.speaker_count == 2
    assert len(assignments) == 0


# ---------------------------------------------------------------------------
# Property 20: Engine failure propagates without persisting a completed state (Task 13.3)
# Feature: speaker-identification, Property 20: Engine failure propagates without persisting a completed Diarization
# Validates: Requirements 9.3, 10.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_20_engine_failure_propagates_without_completed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engine exception -> propagates, and no Diarization is left in 'completed'."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=2)

    engine = AsyncMock()
    engine.diarize.side_effect = RuntimeError("diar-engine crashed")
    engine.capabilities = MagicMock(
        return_value=DiarizationCapabilities(is_local=True, provider_name="diar-engine-local")
    )

    with (
        patch("app.diarization.worker.create_diarization_engine", return_value=engine),
        pytest.raises(RuntimeError, match="diar-engine crashed"),
    ):
        await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)

    async with session_factory() as session:
        completed = (
            await session.execute(
                select(Diarization).where(
                    Diarization.meeting_id == meeting_id,
                    Diarization.diarization_state == "completed",
                )
            )
        ).scalars().all()
    assert len(completed) == 0


# ---------------------------------------------------------------------------
# Property 18: Preservation of the Meeting's ProcessState (Task 13.4)
# Feature: speaker-identification, Property 18: Preservation of the Meeting's ProcessState
# Validates: Requirements 9.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(initial_state=st.sampled_from(["queued", "recording", "transcribing", "completed", "failed"]))
@pytest.mark.asyncio
async def test_property_18_preserves_meeting_process_state(
    session_factory: async_sessionmaker[AsyncSession], initial_state: str
) -> None:
    """The Meeting's ProcessState remains unchanged after diarization."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(
        session_factory, meeting_id, num_turns=2, meeting_state=initial_state
    )

    segments = [SpeakerSegment(raw_label="SPEAKER_00", start_ms=0, end_ms=2000)]
    engine = _mock_engine(segments=segments)
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)

    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
    assert meeting is not None
    assert meeting.process_state == initial_state


# ---------------------------------------------------------------------------
# Property 17: Every state change records a UTC timestamp (Task 13.5)
# Feature: speaker-identification, Property 17: Every state change records a UTC timestamp
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_17_utc_timestamp_on_final_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The persisted Diarization records updated_at in UTC."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=1)

    segments = [SpeakerSegment(raw_label="SPEAKER_00", start_ms=0, end_ms=1000)]
    engine = _mock_engine(segments=segments)
    before = datetime.now(UTC)
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)
    after = datetime.now(UTC)

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarization).where(Diarization.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()

    assert diar is not None
    assert diar.updated_at is not None
    updated = diar.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    assert before <= updated <= after


# ---------------------------------------------------------------------------
# Example tests for the worker (Task 13.6)
# Validates: Requirements 1.5, 1.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_nonexistent_meeting_acks_without_persisting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Req 1.5: nonexistent meeting_id -> ack without persisting (no exception)."""
    await _process_diarization_for_seeded_recording({"meeting_id": "no-existe"}, session_factory)
    async with session_factory() as session:
        assert (await session.execute(select(Diarization))).scalars().all() == []


@pytest.mark.asyncio
async def test_example_without_transcript_acks_without_persisting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Req 1.6: Meeting without a Transcript -> ack without persisting (no exception)."""
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting(meeting_id))
        session.add(_create_recording(meeting_id))
    await _process_diarization_for_seeded_recording({"meeting_id": meeting_id}, session_factory)
    async with session_factory() as session:
        assert (await session.execute(select(Diarization))).scalars().all() == []


@pytest.mark.asyncio
async def test_diarization_uses_recording_from_meeting_not_queue_audio_ref(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A queue-supplied reference cannot substitute another meeting's recording."""
    meeting_id = str(uuid.uuid4())
    foreign_meeting_id = str(uuid.uuid4())
    persisted_audio_ref = "synthetic/owned-recording.webm"
    foreign_audio_ref = "synthetic/foreign-recording.webm"

    async with session_factory() as session, session.begin():
        session.add(_create_meeting(meeting_id))
        session.add(_create_meeting(foreign_meeting_id))
        session.add(_create_recording(meeting_id, persisted_audio_ref))
        session.add(_create_recording(foreign_meeting_id, foreign_audio_ref))
        transcript, turns = _create_transcript_with_turns(meeting_id, num_turns=1)
        session.add(transcript)
        session.add_all(turns)

    engine = _mock_engine(segments=[])
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording(
            {"meeting_id": meeting_id, "audio_ref": foreign_audio_ref},
            session_factory,
        )

    engine.diarize.assert_awaited_once()
    assert engine.diarize.await_args is not None
    assert engine.diarize.await_args.args[0] == persisted_audio_ref


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "recording"])
async def test_diarization_rejects_mismatched_queue_identity(
    session_factory: async_sessionmaker[AsyncSession], mismatch: str
) -> None:
    """Jobs must bind both owner and recording before invoking diarization."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=1)
    async with session_factory() as session:
        recording = (
            await session.execute(
                select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
            )
        ).scalar_one()

    message = {
        "meeting_id": meeting_id,
        "owner_id": "test-user",
        "recording_id": recording.id,
    }
    if mismatch == "owner":
        message["owner_id"] = "different-owner"
    else:
        message["recording_id"] = str(uuid.uuid4())

    engine = _mock_engine(segments=[])
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording(message, session_factory)

    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        diarizations = await session.execute(select(Diarization))
        assert diarizations.scalars().all() == []


@pytest.mark.asyncio
async def test_worker_persists_measured_overlap_for_assignments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persist the positive overlap that justified each speaker assignment."""
    meeting_id = str(uuid.uuid4())
    await _seed_complete_meeting(session_factory, meeting_id, num_turns=1)

    engine = _mock_engine(
        segments=[SpeakerSegment(raw_label="SPEAKER_00", start_ms=200, end_ms=800)]
    )
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization_for_seeded_recording(
            {"meeting_id": meeting_id}, session_factory
        )

    from app.infra.models import SpeakerAssignment

    async with session_factory() as session:
        assignment = (
            await session.execute(
                select(SpeakerAssignment).where(
                    SpeakerAssignment.diarization_id
                    == select(Diarization.id)
                    .where(Diarization.meeting_id == meeting_id)
                    .scalar_subquery()
                )
            )
        ).scalar_one()

    assert getattr(assignment, "overlap_ms", None) == 600
