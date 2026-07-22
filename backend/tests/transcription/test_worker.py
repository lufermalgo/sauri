"""Tests for the transcription worker (worker.py).

# Feature: transcripcion-asr
Tasks: 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15, 8.16
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from hypothesis import given, HealthCheck, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import Meeting, SpeechTurn, Transcript
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
from app.transcription.worker import _process_transcription


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
        created_at=datetime.now(timezone.utc),
    )


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

segment_strategy = st.fixed_dictionaries(
    {
        "texto": st.text(min_size=1, max_size=50),
        "inicio_ms": st.integers(min_value=0, max_value=10_000_000),
        "fin_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(lambda s: s["fin_ms"] >= s["inicio_ms"])


# ---------------------------------------------------------------------------
# Property 16: Invalid input doesn't persist or raise an exception (Task 8.6)
# Feature: transcripcion-asr, Property 16: Invalid input
# Validates: Requirements 1.3, 1.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(message=invalid_message_strategy)
@pytest.mark.asyncio
async def test_property_16_invalid_input_does_not_persist(
    session_factory: async_sessionmaker, message: dict
):
    """Invalid message -> finishes with no exception and nothing persisted."""
    # Should not raise
    await _process_transcription(message, session_factory)

    # No Transcript should exist
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Property 14: State machine correctness (Task 8.7)
# Feature: transcripcion-asr, Property 14: State machine
# Validates: Requirements 8.1, 8.2, 8.3, 8.5
# ---------------------------------------------------------------------------

# Generate all valid (state, event) pairs
valid_pairs = []
for state, events in VALID_TRANSITIONS.items():
    for event in events:
        valid_pairs.append((state, event))

invalid_pairs = []
all_events = set()
for events in VALID_TRANSITIONS.values():
    all_events.update(events.keys())
for state in STATES:
    transitions = VALID_TRANSITIONS.get(state, {})
    for event in all_events:
        if event not in transitions:
            invalid_pairs.append((state, event))


@given(pair=st.sampled_from(valid_pairs))
def test_property_14_valid_transition(pair: tuple[str, str]):
    """Valid (state, event) pairs produce successful transitions."""
    state, event = pair
    result = apply_event(state, event)
    assert result.successful is True
    expected = VALID_TRANSITIONS[state][event]
    assert result.new_state == expected


@given(pair=st.sampled_from(invalid_pairs))
def test_property_14_invalid_transition(pair: tuple[str, str]):
    """Invalid (state, event) pairs produce successful=False."""
    state, event = pair
    result = apply_event(state, event)
    assert result.successful is False
    assert result.new_state == state


@given(state=st.sampled_from(list(TERMINAL_STATES)))
def test_property_14_terminal_state_immutable(state: str):
    """Terminal states are immutable against any event."""
    for event in all_events:
        result = apply_event(state, event)
        assert result.successful is False
        assert result.new_state == state


# ---------------------------------------------------------------------------
# Property 15: History recorded on every transition (Task 8.8)
# Feature: transcripcion-asr, Property 15: History
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pair=st.sampled_from(valid_pairs))
@pytest.mark.asyncio
async def test_property_15_history_recorded(
    session_factory: async_sessionmaker, pair: tuple[str, str]
):
    """Every valid transition creates a StateHistory record."""
    from app.infra.models import StateHistory
    from app.meetings.service import record_transition
    from sqlalchemy import select

    initial_state, event = pair
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state=initial_state)
            session.add(meeting)

    async with session_factory() as session:
        async with session.begin():
            meeting = await session.get(Meeting, meeting_id)
            result = await record_transition(session, meeting, event)

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
# Feature: transcripcion-asr, Property 7: Segment->turn mapping
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
    session_factory: async_sessionmaker,
    segments: list[TranscriptionSegment],
):
    """The worker maps segments to turns in ascending order by position."""
    meeting_id = str(uuid.uuid4())

    # Setup: create meeting in recording state
    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    asr_result = TranscriptionResult(
        segments=segments, language="es-CO", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

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
# Feature: transcripcion-asr, Property 9: Language selection
# Validates: Requirements 6.3, 6.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    engine_language=st.one_of(
        st.just(None),
        st.just(""),
        st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=5,
        ),
    )
)
@pytest.mark.asyncio
async def test_property_9_language_selection(
    session_factory: async_sessionmaker, engine_language: str | None
):
    """language = result.language if non-empty, otherwise 'es-CO'."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

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
        await _process_transcription(message, session_factory)

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
        assert trans.language == "es-CO"


# ---------------------------------------------------------------------------
# Property 12: Provider metadata recording (Task 8.11)
# Feature: transcripcion-asr, Property 12: Provider metadata
# Validates: Requirements 7.5
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    is_local=st.booleans(),
    supports_turns=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_12_provider_metadata(
    session_factory: async_sessionmaker,
    is_local: bool,
    supports_turns: bool,
):
    """The Transcript records provider and supports_turns per the engine's capabilities."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

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
        await _process_transcription(message, session_factory)

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
# Feature: transcripcion-asr, Property 8: No segments
# Validates: Requirements 5.6, 7.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_8_no_segments_does_not_persist(
    session_factory: async_sessionmaker,
):
    """Empty segment list -> no Transcript persisted, state -> failed."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    asr_result = TranscriptionResult(
        segments=[], language="es-CO", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalar_one_or_none() is None

        # Meeting should be in failed
        meeting = await session.get(Meeting, meeting_id)
        assert meeting.process_state == "failed"


# ---------------------------------------------------------------------------
# Property 17: Engine failure propagates without persisting (Task 8.13)
# Feature: transcripcion-asr, Property 17: Failure propagates
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_17_engine_failure_propagates(
    session_factory: async_sessionmaker,
):
    """Engine exception propagates without persisting a Transcript."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    mock_engine = AsyncMock()
    mock_engine.transcribe.side_effect = RuntimeError("ASR engine crashed")

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        with pytest.raises(RuntimeError, match="ASR engine crashed"):
            await _process_transcription(message, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcript))
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Property 10: Uniqueness of the Transcript per Meeting (Task 8.14)
# Feature: transcripcion-asr, Property 10: Uniqueness
# Validates: Requirements 7.1, 9.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_10_transcript_uniqueness(
    session_factory: async_sessionmaker,
):
    """Reprocessing the same message doesn't create duplicates (UniqueConstraint)."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
    asr_result = TranscriptionResult(
        segments=segments, language="es-CO", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    # First processing — succeeds
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

    # Second processing — should fail with IntegrityError (unique constraint)
    # Reset meeting state for the second attempt
    async with session_factory() as session:
        async with session.begin():
            meeting = await session.get(Meeting, meeting_id)
            meeting.process_state = "recording"

    from sqlalchemy.exc import IntegrityError

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        with pytest.raises(IntegrityError):
            await _process_transcription(message, session_factory)

    # Still only one Transcript
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcripts = result.scalars().all()

    assert len(transcripts) == 1


# ---------------------------------------------------------------------------
# Property 11: Persistence atomicity (Task 8.15)
# Feature: transcripcion-asr, Property 11: Atomicity
# Validates: Requirements 7.3, 7.4, 9.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_11_atomicity_rollback(
    session_factory: async_sessionmaker,
):
    """Failure during persistence -> full rollback, nothing partial."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
    asr_result = TranscriptionResult(
        segments=segments, language="es-CO", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    # Patch record_transition to fail AFTER repo.create is called
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        with patch(
            "app.transcription.worker.record_transition",
            side_effect=RuntimeError("DB failure during transition"),
        ):
            with pytest.raises(RuntimeError, match="DB failure"):
                await _process_transcription(message, session_factory)

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
async def test_example_preferred_language_es_co(
    session_factory: async_sessionmaker,
):
    """The worker invokes the engine with preferred_language='es-CO'."""
    meeting_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            meeting = _create_meeting_in_db(meeting_id, state="recording")
            session.add(meeting)

    segments = [TranscriptionSegment(text="test", start_ms=0, end_ms=500)]
    asr_result = TranscriptionResult(
        segments=segments, language="es-CO", supports_turns=True
    )
    capabilities = ASRCapabilities(supports_turns=True, is_local=True)

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = asr_result
    mock_engine.capabilities = MagicMock(return_value=capabilities)

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

    # Verify the engine was called with preferred_language="es-CO"
    mock_engine.transcribe.assert_called_once()
    call_args = mock_engine.transcribe.call_args
    options = call_args[0][1]
    assert isinstance(options, TranscriptionOptions)
    assert options.preferred_language == "es-CO"
