"""Property tests for the transcription pipeline, meeting-capture-transcription spec.

# Feature: meeting-capture-transcription, Property 7: Transcript temporal invariant
# Feature: meeting-capture-transcription, Property 8: Transcription language is es-CO
# Feature: meeting-capture-transcription, Property 9: ASREngine interchangeability
Tasks: 10.5, 10.6, 10.7
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SpeechTurn, Transcript
from app.transcription.asr_engine import (
    ASRCapabilities,
    ASREngine,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionSegment,
)
from app.transcription.worker import _process_transcription


def _create_recording_meeting(meeting_id: str) -> Meeting:
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


def _non_overlapping_segments_strategy(
    max_segments: int = 8,
) -> st.SearchStrategy[list[TranscriptionSegment]]:
    """Generates lists of ordered, non-overlapping segments: end_ms[i] <= start_ms[i+1]."""

    def _build(gaps: list[int], durations: list[int]) -> list[TranscriptionSegment]:
        segments: list[TranscriptionSegment] = []
        cursor = 0
        for gap, duration in zip(gaps, durations, strict=True):
            start = cursor + gap
            end = start + duration
            segments.append(
                TranscriptionSegment(text=f"seg-{len(segments)}", start_ms=start, end_ms=end)
            )
            cursor = end
        return segments

    n = st.integers(min_value=1, max_value=max_segments)

    return n.flatmap(
        lambda k: st.tuples(
            st.lists(st.integers(min_value=0, max_value=500), min_size=k, max_size=k),
            st.lists(st.integers(min_value=0, max_value=5000), min_size=k, max_size=k),
        ).map(lambda pair: _build(pair[0], pair[1]))
    )


# ---------------------------------------------------------------------------
# Property 7: Transcript temporal invariant
# Feature: meeting-capture-transcription, Property 7: Transcript temporal invariant
# Validates: Requirements 3.4, 3.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(segments=_non_overlapping_segments_strategy())
@pytest.mark.asyncio
async def test_property_7_temporal_invariant_of_persisted_turns(
    session_factory: async_sessionmaker[AsyncSession], segments: list[TranscriptionSegment]
) -> None:
    """Persisted SpeechTurn rows satisfy 0<=start_ms<=end_ms, are ordered, and don't overlap."""
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_recording_meeting(meeting_id))

    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = TranscriptionResult(
        segments=segments, language="es-CO", supports_turns=True
    )
    mock_engine.capabilities = MagicMock(
        return_value=ASRCapabilities(supports_turns=True, is_local=True)
    )

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

    async with session_factory() as session:
        result = await session.execute(
            select(SpeechTurn)
            .where(
                SpeechTurn.transcript_id.in_(
                    select(Transcript.id).where(Transcript.meeting_id == meeting_id)
                )
            )
            .order_by(SpeechTurn.sequence)
        )
        turns = result.scalars().all()

    assert len(turns) == len(segments)

    # No nominal identity on SpeechTurn (no speaker field)
    assert not hasattr(SpeechTurn, "speaker_id")
    assert not hasattr(SpeechTurn, "speaker")

    previous_end = None
    for turn in turns:
        assert 0 <= turn.start_ms <= turn.end_ms
        if previous_end is not None:
            assert turn.start_ms >= previous_end, "turns must be ordered without overlap"
        previous_end = turn.end_ms


# ---------------------------------------------------------------------------
# Property 8: Transcription language is es-CO
# Feature: meeting-capture-transcription, Property 8: Transcription language is es-CO
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    language_returned_by_engine=st.one_of(
        st.just(None),
        st.just(""),
        st.just("es-CO"),
    )
)
@pytest.mark.asyncio
async def test_property_8_options_fix_es_co_and_transcript_records_es_co(
    session_factory: async_sessionmaker[AsyncSession], language_returned_by_engine: str | None
) -> None:
    """Transcription options always fix es-CO and the persisted Transcript records es-CO."""
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_recording_meeting(meeting_id))

    segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=500)]
    mock_engine = AsyncMock()
    mock_engine.transcribe.return_value = TranscriptionResult(
        segments=segments,
        language=cast(str, language_returned_by_engine),
        supports_turns=True,
    )
    mock_engine.capabilities = MagicMock(
        return_value=ASRCapabilities(supports_turns=True, is_local=True)
    )

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcription.worker.create_asr_engine", return_value=mock_engine):
        await _process_transcription(message, session_factory)

    options_used: TranscriptionOptions = mock_engine.transcribe.call_args.args[1]
    assert options_used.preferred_language == "es-CO"

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcript = result.scalar_one()

    assert transcript.language == "es-CO"


# ---------------------------------------------------------------------------
# Property 9: ASREngine interchangeability
# Feature: meeting-capture-transcription, Property 9: ASREngine interchangeability
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class _ConformantASREngineWithTurns(ASREngine):
    """Conformant fake with turn support (analogous to a local provider)."""

    async def transcribe(
        self, audio_ref: str, options: TranscriptionOptions
    ) -> TranscriptionResult:
        return TranscriptionResult(
            segments=[
                TranscriptionSegment(text="uno", start_ms=0, end_ms=100),
                TranscriptionSegment(text="dos", start_ms=100, end_ms=250),
            ],
            language="es-CO",
            supports_turns=True,
        )

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(supports_turns=True, is_local=True)


class _ConformantASREngineWithoutTurns(ASREngine):
    """Conformant fake without turn support (analogous to a basic cloud provider)."""

    async def transcribe(
        self, audio_ref: str, options: TranscriptionOptions
    ) -> TranscriptionResult:
        return TranscriptionResult(
            segments=[TranscriptionSegment(text="texto único", start_ms=0, end_ms=1000)],
            language="es-CO",
            supports_turns=False,
        )

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(supports_turns=False, is_local=False)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(engine_with_turns=st.booleans())
@pytest.mark.asyncio
async def test_property_9_asr_engine_interchangeability(
    session_factory: async_sessionmaker[AsyncSession], engine_with_turns: bool
) -> None:
    """Any conformant ASREngine produces a valid Transcript with no changes to the worker."""
    meeting_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_create_recording_meeting(meeting_id))

    engine: ASREngine = (
        _ConformantASREngineWithTurns() if engine_with_turns else _ConformantASREngineWithoutTurns()
    )

    message = {"meeting_id": meeting_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(message, session_factory)

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcript = result.scalar_one()

        turns_result = await session.execute(
            select(SpeechTurn)
            .where(SpeechTurn.transcript_id == transcript.id)
            .order_by(SpeechTurn.sequence)
        )
        turns = turns_result.scalars().all()

    assert transcript.language == "es-CO"
    assert transcript.supports_turns == engine.capabilities().supports_turns
    assert len(turns) >= 1
    previous_end = None
    for turn in turns:
        assert 0 <= turn.start_ms <= turn.end_ms
        if previous_end is not None:
            assert turn.start_ms >= previous_end
        previous_end = turn.end_ms
