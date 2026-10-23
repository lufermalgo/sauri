"""Transcription worker — consumes the queue and produces Transcripts.

Subscribes to the "transcribe" topic of the JobQueue. For each message:
1. Creates an ASREngine via the configuration factory.
2. Invokes transcribe(audio_ref, preferred_language="es-CO").
3. If there are segments -> persists Transcript + SpeechTurn -> transitions to "completed".
4. If there are no segments -> transitions to "failed" with cause "engine_failure".

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript
from app.infra.queue import JobQueue
from app.meetings.service import record_transition
from app.transcription.asr_engine import TranscriptionOptions
from app.transcription.factory import create_asr_engine
from app.transcription.repository import TranscriptRepository

logger = logging.getLogger(__name__)


async def _process_transcription(
    message: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    queue: JobQueue | None = None,
) -> None:
    """Processes a message from the transcription queue.

    Args:
        message: Expected: {"meeting_id": str, "audio_ref": str}
        session_factory: Async SQLAlchemy session factory.
        queue: Optional JobQueue; if provided, once the Transcript becomes
            available a Diarization_Message is published to the "diarize"
            topic with the meeting_id (Req. 1.2 of the speaker-identification
            feature).
    """
    # --- Message validation (Req. 1.2, 1.3) ---
    meeting_id = message.get("meeting_id")
    audio_ref = message.get("audio_ref")

    if not meeting_id or not isinstance(meeting_id, str) or not meeting_id.strip():
        logger.warning(
            "Message discarded: meeting_id missing or empty. message=%s", message
        )
        return

    if not audio_ref or not isinstance(audio_ref, str) or not audio_ref.strip():
        logger.warning(
            "Message discarded: audio_ref missing or empty. message=%s", message
        )
        return

    # --- Load Meeting (Req. 1.4) ---
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)

    if meeting is None:
        logger.warning(
            "Message discarded: Meeting not found for meeting_id=%s",
            meeting_id,
        )
        return

    logger.info("Processing transcription for meeting_id=%s", meeting_id)

    # Initial transition recording -> transcribing (Req. 8.1)
    async with session_factory() as session, session.begin():
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None:
            logger.error("Meeting not found: %s", meeting_id)
            return
        if meeting.process_state == "recording":
            await record_transition(session, meeting, "recording_uploaded")

    # 1. Create the ASR engine via the factory (selects provider by config)
    engine = create_asr_engine()

    async with session_factory() as session:
        recording = (
            await session.execute(
                select(SessionRecording).where(
                    SessionRecording.meeting_id == meeting_id
                )
            )
        ).scalar_one_or_none()
    audio_duration_seconds = recording.duration_seconds if recording else None

    # 2. Transcribe with the preferred language es-CO (Req. 3.2)
    options = TranscriptionOptions(preferred_language="es-CO")
    started_at = time.monotonic()
    try:
        result = await engine.transcribe(audio_ref, options)
    except httpx.TimeoutException:
        elapsed_seconds = time.monotonic() - started_at
        async with session_factory() as session, session.begin():
            meeting = await session.get(Meeting, meeting_id)
            if meeting is not None:
                await record_transition(session, meeting, "engine_failed")
        logger.error(
            "Transcription timed out for meeting_id=%s; audio_duration_seconds=%s; "
            "elapsed_seconds=%.2f; meeting failed and the full recording will not be retried",
            meeting_id,
            audio_duration_seconds,
            elapsed_seconds,
        )
        return
    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "ASR completed for meeting_id=%s; audio_duration_seconds=%s; elapsed_seconds=%.2f",
        meeting_id,
        audio_duration_seconds,
        elapsed_seconds,
    )

    # 3. Evaluate the result and persist
    transcript_created = False
    async with session_factory() as session, session.begin():
        # Re-fetch meeting within the transaction for state transitions
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None:
            logger.error("Meeting not found: %s", meeting_id)
            return

        if result.segments:
            # Text was produced -> persist Transcript and turns (Req. 3.4, 3.5)
            capabilities = engine.capabilities()

            transcript = Transcript(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                language=result.language or "es-CO",
                provider="local" if capabilities.is_local else "cloud",
                supports_turns=capabilities.supports_turns,
                expires_at=None,
                created_at=datetime.now(UTC),
            )

            turns = []
            for sequence, segment in enumerate(result.segments, start=1):
                turn = SpeechTurn(
                    id=str(uuid.uuid4()),
                    transcript_id=transcript.id,
                    text=segment.text,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    sequence=sequence,
                )
                turns.append(turn)

            repo = TranscriptRepository(session_factory)
            await repo.create(session, transcript, turns)
            transcript_created = True

            # Transition to "completed" (Req. 3.6)
            transition = await record_transition(
                session, meeting, "transcription_completed"
            )

            if transition.successful:
                logger.info(
                    "Transcription completed for meeting_id=%s (%d segments)",
                    meeting_id,
                    len(result.segments),
                )
            else:
                logger.warning(
                    "Transition to completed rejected for meeting_id=%s",
                    meeting_id,
                )
        else:
            # No text despite spoken audio -> engine failure (Req. 3.7)
            transition = await record_transition(
                session, meeting, "engine_failed"
            )

            if transition.successful:
                logger.warning(
                    "Transcription with no text for meeting_id=%s -> failed state",
                    meeting_id,
                )
            else:
                logger.warning(
                    "Transition to failed rejected for meeting_id=%s",
                    meeting_id,
                )

    # Enqueue the Diarization_Message once the Transcript transaction is
    # committed (Req. 1.2 of the speaker-identification feature). Doesn't
    # alter the Meeting's ProcessState (Req. 9.5).
    if queue is not None and transcript_created:
        await queue.publish("diarize", {"meeting_id": meeting_id})
        logger.info(
            "Diarization_Message enqueued for meeting_id=%s (topic 'diarize')",
            meeting_id,
        )


async def start_worker(
    queue: JobQueue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Starts the transcription worker: subscribes to the 'transcribe' topic.

    Args:
        queue: Already-connected JobQueue instance.
        session_factory: SQLAlchemy session factory for persistence.
    """

    async def handler(message: dict[str, Any]) -> None:
        await _process_transcription(message, session_factory, queue)

    await queue.subscribe("transcribe", handler)
    logger.info("Transcription worker subscribed to the 'transcribe' topic")
