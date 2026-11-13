"""Queue consumer for admitted exact revisions; legacy jobs retain their old handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.diarization_engine import DiarizationOptions
from app.diarization.factory import create_diarization_engine
from app.infra.models import (
    Diarization,
    ProcessingRevision,
    ProcessingRevisionOutbox,
    ProcessingStage,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
)
from app.infra.object_store import ObjectStore
from app.infra.queue import JobQueue
from app.meetings.speaker_excerpt_service import ManagedDecoderProcess, SpeakerExcerptService
from app.transcription.asr_engine import TranscriptionOptions
from app.transcription.factory import create_asr_engine
from app.transcription.processing_pipeline import ProcessingPipeline


@dataclass(frozen=True)
class _ExcerptCandidate:
    start_ms: int
    end_ms: int
    vad_positive_windows: int
    vad_window_count: int
    assigned_speaker_id: str


def _probe_audio() -> tuple[str, ...]:
    return ("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", "-i", "pipe:0")


def _decode_audio(start_ms: int, end_ms: int) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-v",
        "error",
        "-i",
        "pipe:0",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-t",
        f"{(end_ms - start_ms) / 1000:.3f}",
        "-f",
        "wav",
        "pipe:1",
    )


def create_pipeline(sessions: async_sessionmaker[AsyncSession], store: ObjectStore) -> ProcessingPipeline:
    """Use real configured providers and bounded, decoded speaker-specific audio."""
    excerpt_service = SpeakerExcerptService(
        object_store=store,
        decoder=ManagedDecoderProcess(),
        decode_interval=_decode_audio,
        read_interval=_decode_audio,
        probe_audio=_probe_audio,
    )

    async def transcribe(audio_ref: str) -> dict[str, Any]:
        result = await create_asr_engine().transcribe(audio_ref, TranscriptionOptions())
        return {
            "language": result.language,
            "supports_turns": result.supports_turns,
            "segments": [
                {"text": part.text, "start_ms": part.start_ms, "end_ms": part.end_ms} for part in result.segments
            ],
        }

    async def diarize(audio_ref: str, recording: SessionRecording) -> dict[str, Any]:
        # The reference and bounded duration both come from the admitted recording.
        duration_ms = recording.duration_seconds * 1000
        result = await create_diarization_engine().diarize(audio_ref, DiarizationOptions(duration_ms=duration_ms))
        return {
            "speakers": list(dict.fromkeys(segment.raw_label for segment in result.segments)),
            "segments": [
                {"raw_label": part.raw_label, "start_ms": part.start_ms, "end_ms": part.end_ms}
                for part in result.segments
            ],
        }

    async def validate_excerpts(
        recording: SessionRecording, revision: ProcessingRevision, speakers: list[Speaker]
    ) -> dict[str, str]:
        async with sessions() as session:
            transcript = await session.scalar(
                select(Transcript).where(
                    Transcript.meeting_id == recording.meeting_id,
                    Transcript.processing_revision_id == revision.id,
                )
            )
            stage = await session.scalar(
                select(ProcessingStage).where(
                    ProcessingStage.processing_revision_id == revision.id,
                    ProcessingStage.stage == "diarization",
                    ProcessingStage.status == "completed",
                )
            )
            if transcript is None:
                raise ValueError("validated excerpts unavailable")
            diarization = await session.scalar(
                select(Diarization).where(
                    Diarization.processing_revision_id == revision.id, Diarization.transcript_id == transcript.id
                )
            )
            if diarization is None:
                raise ValueError("validated excerpts unavailable")
            assignments = (
                await session.execute(
                    select(SpeakerAssignment, SpeechTurn)
                    .join(SpeechTurn, SpeechTurn.id == SpeakerAssignment.turn_id)
                    .where(SpeakerAssignment.diarization_id == diarization.id)
                )
            ).all()
            segments = stage.output["segments"] if stage is not None and stage.output is not None else []
        excerpts: dict[str, str] = {}
        for speaker in speakers:
            # Only ASR speech explicitly assigned to this diarized speaker can
            # make an interval eligible. A speech turn from another speaker
            # must never validate an otherwise silent excerpt.
            assigned = [turn for assignment, turn in assignments if assignment.speaker_id == speaker.id]
            key = speaker.raw_label if segments else speaker.id
            candidates = []
            source_segments = (
                [segment for segment in segments if segment["raw_label"] == speaker.raw_label]
                if segments
                else [{"start_ms": turn.start_ms, "end_ms": turn.end_ms} for turn in assigned]
            )
            for segment in source_segments:
                start, end = segment["start_ms"], segment["end_ms"]
                if end - start > excerpt_service.MAX_EXCERPT_DURATION_MS:
                    end = start + excerpt_service.MAX_EXCERPT_DURATION_MS
                speech_overlap = any(turn.start_ms < end and turn.end_ms > start for turn in assigned)
                candidates.append(_ExcerptCandidate(start, end, int(speech_overlap), 1, key))
            excerpt = await excerpt_service.derive(
                recording_id=recording.id,
                revision_id=revision.revision,
                speaker_id=key,
                object_key=recording.audio_ref,
                audio_duration_ms=recording.duration_seconds * 1000,
                candidates=candidates,
            )
            excerpts[key] = excerpt.reference
        return excerpts

    return ProcessingPipeline(
        sessions, transcription_provider=transcribe, diarization_provider=diarize, excerpt_validator=validate_excerpts
    )


async def handle_revision_event(
    message: dict[str, Any], sessions: async_sessionmaker[AsyncSession], pipeline: ProcessingPipeline
) -> None:
    """Reject forged/stale bindings; only a persisted outbox event drives work."""
    revision_id = message.get("processing_revision_id")
    recording_id = message.get("recording_id")
    event_type = message.get("event_type")
    async with sessions() as session:
        event = await session.get(ProcessingRevisionOutbox, message.get("event_id"))
        if (
            event is None
            or event.processing_revision_id != revision_id
            or event.recording_id != recording_id
            or event.event_type != event_type
        ):
            return
        revision = await session.get(ProcessingRevision, revision_id)
        if revision is None or revision.recording_id != recording_id:
            return
    if event_type == "processing_revision_admitted":
        await pipeline.process_stage(revision_id, "transcription")
    elif event_type == "transcription_completed":
        await pipeline.process_stage(revision_id, "diarization")
    elif event_type == "diarization_completed":
        await pipeline.finalize(revision_id)


async def start_processing_worker(
    queue: JobQueue, sessions: async_sessionmaker[AsyncSession], store: ObjectStore
) -> None:
    pipeline = create_pipeline(sessions, store)

    async def handler(message: dict[str, Any]) -> None:
        await handle_revision_event(message, sessions, pipeline)

    await queue.subscribe("processing_revision", handler)
