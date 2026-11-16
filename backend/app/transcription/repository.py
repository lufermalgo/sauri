"""Persistence repository for Transcript and SpeechTurn."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.diarization.remap import Span, remap_spans
from app.infra.models import (
    Diarization,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
    TranscriptWord,
    WordSpeakerAssignment,
)
from app.transcription.asr_engine import TranscriptionSegment, TranscriptionWord


class TranscriptRepository:
    """SQLAlchemy repository for Transcript — metadata and turns in one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        session: AsyncSession,
        transcript: Transcript,
        turns: list[SpeechTurn],
    ) -> Transcript:
        """Adds a transcript and its speech turns to the given session.

        Doesn't open, close, or commit the session: the caller (worker)
        controls the transaction and decides when to commit or roll back, so
        a later failure (e.g. the state transition) can revert both the
        Transcript and its SpeechTurn rows atomically.
        """
        session.add(transcript)
        for turn in turns:
            session.add(turn)
        await session.flush()
        return transcript

    async def get_by_meeting(self, meeting_id: str) -> Transcript | None:
        """Gets the transcript associated with a meeting along with its turns."""
        async with self._session_factory() as session:
            stmt = (
                select(Transcript)
                .where(Transcript.meeting_id == meeting_id)
                .options(selectinload(Transcript.turns))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()


async def replace_transcript_content(
    session: AsyncSession,
    transcript: Transcript,
    *,
    language: str,
    provider: str,
    supports_turns: bool,
    segments: Sequence[TranscriptionSegment],
    words: Sequence[TranscriptionWord],
    now: datetime,
) -> None:
    """Swap a regenerated transcript's text into the same Transcript row (#1053).

    The row keeps its identity, so summaries and speaker revisions stay attached. The
    latest completed speaker detection is re-attributed to the new turns and words by
    time overlap; older revisions lose their assignments, which would dangle.
    """
    latest = await session.scalar(
        select(Diarization).where(
            Diarization.meeting_id == transcript.meeting_id, Diarization.diarization_state == "completed"
        ).order_by(Diarization.processing_revision.desc()).limit(1)
    )
    old_turns: list[Span[str]] = []
    old_words: list[Span[tuple[str | None, str, list[dict[str, object]] | None]]] = []
    if latest is not None:
        old_turns = [
            Span(start, end, speaker_id)
            for start, end, speaker_id in (await session.execute(
                select(SpeechTurn.start_ms, SpeechTurn.end_ms, SpeakerAssignment.speaker_id)
                .join(SpeakerAssignment, SpeakerAssignment.turn_id == SpeechTurn.id)
                .where(SpeechTurn.transcript_id == transcript.id, SpeakerAssignment.diarization_id == latest.id)
            )).all()
        ]
        old_words = [
            Span(start, end, (speaker_id, state, candidates))
            for start, end, speaker_id, state, candidates in (await session.execute(
                select(
                    TranscriptWord.start_ms, TranscriptWord.end_ms, WordSpeakerAssignment.speaker_id,
                    WordSpeakerAssignment.state, WordSpeakerAssignment.candidates_json,
                )
                .join(WordSpeakerAssignment, WordSpeakerAssignment.word_id == TranscriptWord.id)
                .where(TranscriptWord.transcript_id == transcript.id, WordSpeakerAssignment.diarization_id == latest.id)
            )).all()
        ]

    turn_ids = select(SpeechTurn.id).where(SpeechTurn.transcript_id == transcript.id)
    word_ids = select(TranscriptWord.id).where(TranscriptWord.transcript_id == transcript.id)
    await session.execute(delete(SpeakerAssignment).where(SpeakerAssignment.turn_id.in_(turn_ids)))
    await session.execute(delete(WordSpeakerAssignment).where(WordSpeakerAssignment.word_id.in_(word_ids)))
    await session.execute(delete(SpeechTurn).where(SpeechTurn.transcript_id == transcript.id))
    await session.execute(delete(TranscriptWord).where(TranscriptWord.transcript_id == transcript.id))

    transcript.language, transcript.provider, transcript.supports_turns = language, provider, supports_turns
    transcript.created_at = now
    turns = [
        SpeechTurn(
            id=str(uuid.uuid4()), transcript_id=transcript.id, text=segment.text,
            start_ms=segment.start_ms, end_ms=segment.end_ms, sequence=sequence,
        )
        for sequence, segment in enumerate(segments, start=1)
    ]
    new_words = [
        TranscriptWord(
            id=str(uuid.uuid4()), transcript_id=transcript.id, sequence=sequence, text=word.text,
            start_ms=word.start_ms, end_ms=word.end_ms, probability=word.probability,
            timing_repaired=word.timing_repaired,
        )
        for sequence, word in enumerate(words, start=1)
    ]
    session.add_all([*turns, *new_words])
    await session.flush()  # The assignments below reference these rows without a relationship.
    if latest is None:
        return
    turn_speakers = remap_spans(old_turns, [(turn.start_ms, turn.end_ms) for turn in turns], nearest=True)
    session.add_all([
        SpeakerAssignment(
            id=str(uuid.uuid4()), diarization_id=latest.id, turn_id=turn.id, speaker_id=speaker_id, overlap_ms=None
        )
        for turn, speaker_id in zip(turns, turn_speakers, strict=True) if speaker_id is not None
    ])
    word_attributions = remap_spans(old_words, [(word.start_ms, word.end_ms) for word in new_words], nearest=False)
    session.add_all([
        WordSpeakerAssignment(
            diarization_id=latest.id, word_id=word.id,
            speaker_id=attribution[0] if attribution else None,
            state=attribution[1] if attribution else "unassigned",
            candidates_json=attribution[2] if attribution else None,
        )
        for word, attribution in zip(new_words, word_attributions, strict=True)
    ] if old_words else [])
    await session.flush()
