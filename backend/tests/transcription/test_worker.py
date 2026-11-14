"""Tests for the transcription worker (worker.py).

# Feature: transcription-asr
Tasks: 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15, 8.16
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypeGuard, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript
from app.meetings.state_machine import (
    STATES,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    apply_event,
)
from app.transcription.asr_engine import (
    ASRCapabilities,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionSegment,
)
from app.transcription.worker import _process_transcription as _process_transcription_worker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_meeting_in_db(meeting_id: str, state: str = "recording") -> Meeting:
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


def _create_recording_in_db(
    meeting_id: str, audio_ref: str = "audio/test.webm"
) -> SessionRecording:
    return SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        audio_ref=audio_ref,
        video_ref=None,
        duration_seconds=12,
        interrupted=False,
        expires_at=None,
        finished_at=datetime.now(UTC),
    )


async def _process_transcription_for_seeded_recording(
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
    await _process_transcription_worker(bound_message, session_factory)


# ---------------------------------------------------------------------------
# Strategies for worker tests
# ---------------------------------------------------------------------------

invalid_message_strategy = st.one_of(
    # Missing meeting_id
    st.fixed_dictionaries({"audio_ref": st.text(min_size=1, max_size=20)}),
    # Empty meeting_id
    st.fixed_dictionaries(
        {"meeting_id": st.just(""), "audio_ref": st.text(min_size=1, max_size=20)}
    ),
    # Only spaces meeting_id
    st.fixed_dictionaries(
        {"meeting_id": st.just("   "), "audio_ref": st.text(min_size=1, max_size=20)}
    ),
    # Missing audio_ref
    st.fixed_dictionaries({"meeting_id": st.uuids().map(str)}),
    # Empty audio_ref
    st.fixed_dictionaries({"meeting_id": st.uuids().map(str), "audio_ref": st.just("")}),
    # Only spaces audio_ref
    st.fixed_dictionaries(
        {"meeting_id": st.uuids().map(str), "audio_ref": st.just("  ")}
    ),
    # Empty dict
    st.just({}),
)

def _is_valid_segment(segment: dict[str, Any]) -> TypeGuard[dict[str, Any]]:
    return bool(segment["fin_ms"] >= segment["inicio_ms"])


segment_strategy: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {
        "texto": st.text(min_size=1, max_size=50),
        "inicio_ms": st.integers(min_value=0, max_value=10_000_000),
        "fin_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(_is_valid_segment)


# ---------------------------------------------------------------------------
# Property 16: Invalid input doesn't persist or raise an exception (Task 8.6)
# Feature: transcription-asr, Property 16: Invalid input
# Validates: Requirements 1.3, 1.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(message=invalid_message_strategy)
@pytest.mark.asyncio
async def test_property_16_invalid_input_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession], message: dict[str, Any]
) -> None:
    """Invalid message -> finishes with no exception and nothing persisted."""
    # Should not raise
    await _process_transcription_for_seeded_recording(message, session_factory)

    # No Transcript should exist
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Property 14: State machine correctness (Task 8.7)
# Feature: transcription-asr, Property 14: State machine
# Validates: Requirements 8.1, 8.2, 8.3, 8.5
# ---------------------------------------------------------------------------

# Generate all valid (state, event) pairs
valid_pairs = []
for state, events in VALID_TRANSITIONS.items():
    for event in events:
        valid_pairs.append((state, event))

invalid_pairs = []
all_events: set[str] = set()
for events in VALID_TRANSITIONS.values():
    all_events.update(events.keys())
for state in STATES:
    transitions = VALID_TRANSITIONS.get(state, {})
    for event in all_events:
        if event not in transitions:
            invalid_pairs.append((state, event))


@given(pair=st.sampled_from(valid_pairs))
def test_property_14_valid_transition(pair: tuple[str, str]) -> None:
    """Valid (state, event) pairs produce successful transitions."""
    state, event = pair
    result = apply_event(state, event)
    assert result.successful is True
    expected = VALID_TRANSITIONS[state][event]
    assert result.new_state == expected


@given(pair=st.sampled_from(invalid_pairs))
def test_property_14_invalid_transition(pair: tuple[str, str]) -> None:
    """Invalid (state, event) pairs produce successful=False."""
    state, event = pair
    result = apply_event(state, event)
    assert result.successful is False
    assert result.new_state == state


@given(state=st.sampled_from(list(TERMINAL_STATES)))
def test_property_14_terminal_state_immutable(state: str) -> None:
    """Terminal states are immutable against any event."""
    for event in all_events:
        result = apply_event(state, event)
        assert result.successful is False
        assert result.new_state == state


# ---------------------------------------------------------------------------
# Property 15: History recorded on every transition (Task 8.8)
# Feature: transcription-asr, Property 15: History
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pair=st.sampled_from(valid_pairs))
@pytest.mark.asyncio
async def test_property_15_history_recorded(
    session_factory: async_sessionmaker[AsyncSession], pair: tuple[str, str]
) -> None:
    """Every valid transition creates a StateHistory record."""
    from sqlalchemy import select

    from app.infra.models import StateHistory
    from app.meetings.service import record_transition

    initial_state, event = pair
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state=initial_state)
        session.add(meeting)

    async with session_factory() as session, session.begin():
        existing_meeting = cast(Meeting, await session.get(Meeting, meeting_id))
        result = await record_transition(session, existing_meeting, event)

    assert result.successful is True

    async with session_factory() as session:
        stmt = select(StateHistory).where(
            StateHistory.meeting_id == meeting_id
        )
        result_query = await session.execute(stmt)
        histories = result_query.scalars().all()

    assert len(histories) == 1
    assert histories[0].state == result.new_state


# ---------------------------------------------------------------------------
# Property 7: Mapping segments to turns preserves order and timestamps (Task 8.9)
# Feature: transcription-asr, Property 7: Segment->turn mapping
# Validates: Requirements 5.5, 7.6
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    segments=st.lists(
        st.builds(
            TranscriptionSegment,
            text=st.text(min_size=1, max_size=50),
            start_ms=st.integers(min_value=0, max_value=10_000_000),
            end_ms=st.integers(min_value=0, max_value=10_000_000),
        ).filter(lambda s: s.end_ms >= s.start_ms),
        min_size=1,
        max_size=10,
    )
)
@pytest.mark.asyncio
async def test_property_7_segment_to_turn_mapping(
    session_factory: async_sessionmaker[AsyncSession],
    segments: list[TranscriptionSegment],
) -> None:
    """The worker maps segments to turns in ascending order by position."""
    meeting_id = str(uuid.uuid4())

    # Setup: create meeting in recording state
    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    asr_result = TranscriptionResult(
        segments=segments, language="es", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    # Verify turns
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(SpeechTurn).where(
                SpeechTurn.transcript_id.in_(
                    select(Transcript.id).where(Transcript.meeting_id == meeting_id)
                )
            )
        )
        turns = result.scalars().all()

    assert len(turns) == len(segments)
    turns_sorted = sorted(turns, key=lambda t: t.sequence)
    for i, turn in enumerate(turns_sorted):
        assert turn.sequence == i + 1
        assert turn.text == segments[i].text
        assert turn.start_ms == segments[i].start_ms
        assert turn.end_ms == segments[i].end_ms


# ---------------------------------------------------------------------------
# Property 9: Selection of the Transcript's language (Task 8.10)
# Feature: transcription-asr, Property 9: Language selection
# Validates: Requirements 6.3, 6.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    engine_language=st.one_of(
        st.just(None),
        st.just(""),
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Lt", "Lm", "Lo")),
            min_size=2,
            max_size=5,
        ),
    )
)
@pytest.mark.asyncio
async def test_property_9_language_selection(
    session_factory: async_sessionmaker[AsyncSession], engine_language: str | None
) -> None:
    """language = result.language if non-empty, otherwise 'es'."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
    asr_result = TranscriptionResult(
        segments=segments,
        language=engine_language if engine_language else "",
        supports_turns=True,
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        trans = result.scalar_one_or_none()

    assert trans is not None
    if engine_language and engine_language.strip():
        assert trans.language == engine_language
    else:
        assert trans.language == "es"


# ---------------------------------------------------------------------------
# Property 12: Provider metadata recording (Task 8.11)
# Feature: transcription-asr, Property 12: Provider metadata
# Validates: Requirements 7.5
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    is_local=st.booleans(),
    supports_turns=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_12_provider_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    is_local: bool,
    supports_turns: bool,
) -> None:
    """The Transcript records provider and supports_turns per the engine's capabilities."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    segments = [TranscriptionSegment(text="test", start_ms=0, end_ms=500)]
    asr_result = TranscriptionResult(
        segments=segments, language="es", supports_turns=supports_turns
    )
    capabilities = ASRCapabilities(supports_turns=supports_turns, is_local=is_local)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        trans = result.scalar_one_or_none()

    assert trans is not None
    expected_provider = "local" if is_local else "cloud"
    assert trans.provider == expected_provider
    assert trans.supports_turns == supports_turns


# ---------------------------------------------------------------------------
# Property 8: Result with no segments produces no Transcript (Task 8.12)
# Feature: transcription-asr, Property 8: No segments
# Validates: Requirements 5.6, 7.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_8_no_segments_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Empty segment list -> no Transcript persisted, state -> failed."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    asr_result = TranscriptionResult(
        segments=[], language="es", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalar_one_or_none() is None

        # Meeting should be in failed
        persisted_meeting = cast(Meeting, await session.get(Meeting, meeting_id))
        assert persisted_meeting.process_state == "failed"


# ---------------------------------------------------------------------------
# Property 17: Engine failure propagates without persisting (Task 8.13)
# Feature: transcription-asr, Property 17: Failure propagates
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_17_engine_failure_propagates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engine exception propagates without persisting a Transcript."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    mock_engine = AsyncMock()
    mock_engine.transcribe.side_effect = RuntimeError("ASR engine crashed")

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch(
        "app.transcription.worker.create_asr_engine", return_value=mock_engine
    ), pytest.raises(RuntimeError, match="ASR engine crashed"):
        await _process_transcription_for_seeded_recording(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_timeout_fails_meeting_without_rethrowing_for_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting_in_db(meeting_id, state="recording"))
        session.add(_create_recording_in_db(meeting_id))

    mock_engine = AsyncMock()
    mock_engine.transcribe.side_effect = httpx.ReadTimeout("ASR request timed out")

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(
            {"meeting_id": meeting_id, "audio_ref": "audio/synthetic.wav"},
            session_factory,
        )

    mock_engine.transcribe.assert_awaited_once()
    async with session_factory() as session:
        persisted_meeting = cast(Meeting, await session.get(Meeting, meeting_id))
        assert persisted_meeting.process_state == "failed"
        assert persisted_meeting.failure_cause == "engine_failed"
        assert await session.get(Transcript, meeting_id) is None


# ---------------------------------------------------------------------------
# Property 10: Uniqueness of the Transcript per Meeting (Task 8.14)
# Feature: transcription-asr, Property 10: Uniqueness
# Validates: Requirements 7.1, 9.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_10_transcript_uniqueness(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reprocessing the same message doesn't create duplicates (UniqueConstraint)."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
    asr_result = TranscriptionResult(
        segments=segments, language="es", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    # First processing — succeeds
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    # Redelivery reuses the persisted transcript rather than invoking ASR again.
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)
    assert mock_engine.transcribe.await_count == 1

    # Still only one Transcript
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcripts = result.scalars().all()

    assert len(transcripts) == 1

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            session.add(Transcript(
                id=str(uuid.uuid4()), meeting_id=meeting_id, language="es", provider="local",
                supports_turns=True, created_at=datetime.now(UTC),
            ))
            await session.flush()


# ---------------------------------------------------------------------------
# Property 11: Persistence atomicity (Task 8.15)
# Feature: transcription-asr, Property 11: Atomicity
# Validates: Requirements 7.3, 7.4, 9.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_11_atomicity_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Failure during persistence -> full rollback, nothing partial."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
    asr_result = TranscriptionResult(
        segments=segments, language="es", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    # Patch record_transition to fail AFTER repo.create is called
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine), patch(
        "app.transcription.worker.record_transition",
        side_effect=RuntimeError("DB failure during transition"),
    ), pytest.raises(RuntimeError, match="DB failure"):
        await _process_transcription_for_seeded_recording(message, session_factory)

    # Verify: no Transcript or SpeechTurn persisted
    from sqlalchemy import select

    async with session_factory() as session:
        trans_result = await session.execute(select(Transcript))
        assert trans_result.scalar_one_or_none() is None

        turns_result = await session.execute(select(SpeechTurn))
        assert turns_result.scalars().all() == []


# ---------------------------------------------------------------------------
# Example test — default preferred language (Task 8.16)
# Validates: Requirements 6.1, 6.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_preferred_language_es(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The worker invokes the engine with preferred_language='es'."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session, session.begin():
        meeting = _create_meeting_in_db(meeting_id, state="recording")
        session.add(meeting)
        session.add(_create_recording_in_db(meeting_id))

    segments = [TranscriptionSegment(text="test", start_ms=0, end_ms=500)]
    asr_result = TranscriptionResult(
        segments=segments, language="es", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    # Verify the engine was called with preferred_language="es"
    mock_engine.transcribe.assert_called_once()
    call_args = mock_engine.transcribe.call_args
    options = call_args[0][1]
    assert isinstance(options, TranscriptionOptions)
    assert options.preferred_language == "es"


@pytest.mark.asyncio
async def test_transcription_uses_audio_ref_from_recording_owned_by_meeting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A queue message cannot substitute another recording's audio reference."""
    meeting_id = str(uuid.uuid4())
    foreign_meeting_id = str(uuid.uuid4())
    persisted_audio_ref = "synthetic/owned-recording.wav"
    foreign_audio_ref = "synthetic/foreign-recording.wav"

    async with session_factory() as session, session.begin():
        session.add(_create_meeting_in_db(meeting_id, state="recording"))
        session.add(_create_meeting_in_db(foreign_meeting_id, state="recording"))
        session.add(
            SessionRecording(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension",
                audio_ref=persisted_audio_ref,
                video_ref=None,
                duration_seconds=12,
                interrupted=False,
                expires_at=None,
                finished_at=datetime.now(UTC),
            )
        )
        session.add(_create_recording_in_db(foreign_meeting_id, foreign_audio_ref))

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment(text="synthetic", start_ms=0, end_ms=100)],
        language="es",
        supports_turns=True,
    )
    mock_engine.capabilities = MagicMock(
        return_value=ASRCapabilities(supports_turns=True, is_local=True)
    )

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(
            {"meeting_id": meeting_id, "audio_ref": foreign_audio_ref}, session_factory
        )

    mock_engine.transcribe.assert_awaited_once()
    assert mock_engine.transcribe.await_args is not None
    assert mock_engine.transcribe.await_args.args[0] == persisted_audio_ref


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "recording"])
async def test_transcription_rejects_mismatched_queue_identity(
    session_factory: async_sessionmaker[AsyncSession], mismatch: str
) -> None:
    """Jobs must bind both owner and recording before invoking the ASR engine."""
    meeting_id = str(uuid.uuid4())
    recording_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting_in_db(meeting_id, state="recording"))
        session.add(
            SessionRecording(
                id=recording_id,
                meeting_id=meeting_id,
                idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension",
                audio_ref="synthetic/owned-recording.wav",
                video_ref=None,
                duration_seconds=12,
                interrupted=False,
                expires_at=None,
                finished_at=datetime.now(UTC),
            )
        )

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment(text="synthetic", start_ms=0, end_ms=100)],
        language="es",
        supports_turns=True,
    )
    mock_engine.capabilities = MagicMock(
        return_value=ASRCapabilities(supports_turns=True, is_local=True)
    )
    message = {
        "meeting_id": meeting_id,
        "audio_ref": "synthetic/owned-recording.wav",
        "owner_id": "test-user",
        "recording_id": recording_id,
    }
    if mismatch == "owner":
        message["owner_id"] = "different-owner"
    else:
        message["recording_id"] = str(uuid.uuid4())

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription_for_seeded_recording(message, session_factory)

    mock_engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        transcripts = await session.execute(select(Transcript))
        assert transcripts.scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "requested", "expected"), [
    (None, None, "es"), ("en", None, "en"), ("auto", None, "auto"), ("es", "en", "en"),
    ("en", "auto", "auto"),
])
async def test_language_precedence_and_detected_language_persistence(
    session_factory, monkeypatch, configured, requested, expected,
):
    if configured is None:
        monkeypatch.delenv("SAURI_DEFAULT_LANGUAGE", raising=False)
    else:
        monkeypatch.setenv("SAURI_DEFAULT_LANGUAGE", configured)
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting_in_db(meeting_id))
        session.add(_create_recording_in_db(meeting_id))
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment("synthetic", 0, 100)], language="fr",
    )
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))
    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}
    if requested:
        message["language"] = requested
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription_for_seeded_recording(message, session_factory)
    assert engine.transcribe.call_args.args[1].preferred_language == expected
    async with session_factory() as session:
        transcript = (await session.execute(select(Transcript))).scalar_one()
        assert transcript.language == "fr"


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "cause"), [
    ("contract", "engine_contract_mismatch"), ("v1", "engine_contract_mismatch"),
    ("auto_missing", "engine_contract_mismatch"), ("value", "invalid_response"),
    ("normalize_failed", "engine_failed"), ("no_word_timestamps", "engine_failed"),
    ("engine_failed", "engine_failed"),
])
async def test_engine_failures_are_persisted_without_leaking_content(
    session_factory, monkeypatch, caplog, failure, cause,
):
    from app.infra.models import StateHistory
    from app.transcription.asr_engine import EngineContractError
    from app.transcription.local_provider import LocalProvider

    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_meeting_in_db(meeting_id, state="transcribing"))
        session.add(_create_recording_in_db(meeting_id))
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(language="")
    private = "/private/audio.wav private transcript content"
    if failure == "contract":
        engine.transcribe.side_effect = EngineContractError(private)
    elif failure == "value":
        engine.transcribe.side_effect = ValueError(private)
    elif failure in {"normalize_failed", "no_word_timestamps", "engine_failed"}:
        response = httpx.Response(422 if failure == "normalize_failed" else 500,
                                  json={"detail": failure, "private": private})
        engine.transcribe.side_effect = httpx.HTTPStatusError(private,
            request=httpx.Request("POST", "http://engine/transcribe"), response=response)
    elif failure == "v1":
        engine = LocalProvider("http://engine")
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, json={"segments": [], "language": "es"},
                                                  request=httpx.Request("POST", "http://engine/transcribe"))
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("app.transcription.local_provider.httpx.AsyncClient", lambda: manager)
    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm", "language": "auto"}
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription_for_seeded_recording(message, session_factory)
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting.process_state == "failed" and meeting.failure_cause == cause
        history = (await session.execute(
            select(StateHistory).where(StateHistory.meeting_id == meeting_id))).scalar_one()
        assert history.state == "failed" and history.failure_cause == cause
        assert (await session.execute(select(Transcript))).scalars().all() == []
    assert private not in caplog.text
    assert "cause=" + cause in caplog.text


@pytest.mark.asyncio
async def test_invalid_default_language_fails_before_worker_subscription(monkeypatch, session_factory):
    from app.transcription.worker import start_worker

    monkeypatch.setenv("SAURI_DEFAULT_LANGUAGE", "spa")
    queue = AsyncMock()
    with pytest.raises(ValueError, match="SAURI_DEFAULT_LANGUAGE"):
        await start_worker(queue, session_factory)
    queue.subscribe.assert_not_called()
