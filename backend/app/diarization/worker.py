"""Diarization worker — consumes the "diarize" queue and produces Diarizations.

Subscribes to the "diarize" topic of the JobQueue. For each message:
1. Validates the meeting_id; loads Meeting, Transcript, and SessionRecording.
2. Creates a DiarizationEngine via the configuration factory.
3. Invokes diarize(audio_ref, DiarizationOptions(duration_ms=...)).
4. Labels speakers and assigns turns by maximum overlap.
5. Persists Diarization + Speakers + Assignments in one transaction (completed state).

Does NOT modify the Meeting's ProcessState (Req. 9.5): it uses its own
independent state machine (state.py) and never invokes record_transition.

Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 6.1, 7.1, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import DiarizationOptions
from app.diarization.factory import create_diarization_engine
from app.diarization.labeling import label_speakers
from app.diarization.repository import DiarizationRepository
from app.diarization.state import apply_diarization_event
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
)
from app.infra.queue import JobQueue
from app.transcription.repository import TranscriptRepository

logger = logging.getLogger(__name__)


async def _process_diarization(
    message: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Processes a Diarization_Message from the "diarize" topic.

    Args:
        message: Expected: {"meeting_id": str}
        session_factory: Async SQLAlchemy session factory.
    """
    # --- Message validation (Req. 1.3, 1.4) ---
    meeting_id = message.get("meeting_id")
    if not meeting_id or not isinstance(meeting_id, str) or not meeting_id.strip():
        logger.warning(
            "Diarization message discarded: meeting_id missing or invalid. message=%s",
            message,
        )
        return

    # --- Load Meeting (Req. 1.5) ---
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        logger.warning(
            "Diarization discarded: Meeting not found for meeting_id=%s",
            meeting_id,
        )
        return

    # --- Load Transcript + turns (Req. 1.6) ---
    transcript_repo = TranscriptRepository(session_factory)
    transcript = await transcript_repo.get_by_meeting(meeting_id)
    if transcript is None:
        logger.warning(
            "Diarization discarded: Transcript not found for meeting_id=%s",
            meeting_id,
        )
        return

    # --- Load SessionRecording for audio_ref and duration ---
    async with session_factory() as session:
        recording = (
            await session.execute(
                select(SessionRecording).where(
                    SessionRecording.meeting_id == meeting_id
                )
            )
        ).scalar_one_or_none()
    if recording is None:
        logger.warning(
            "Diarization discarded: SessionRecording not found for meeting_id=%s",
            meeting_id,
        )
        return

    logger.info("Processing diarization for meeting_id=%s", meeting_id)

    # --- State: pending -> in_progress (Req. 9.1) ---
    transition = apply_diarization_event("pending", "start_process")
    current_state = transition.new_state  # "in_progress"

    # --- Create the engine (Req. 2) ---
    engine = create_diarization_engine()

    # --- Diarize (Req. 10.1: engine exception propagates without persisting) ---
    duration_ms = recording.duration_seconds * 1000
    result = await engine.diarize(
        recording.audio_ref, DiarizationOptions(duration_ms=duration_ms)
    )

    # --- Label speakers (Req. 6) and assign turns (Req. 7) ---
    domain_speakers = label_speakers(result.segments)
    domain_assignments = assign_turns(
        list(transcript.turns), result.segments, domain_speakers
    )

    # --- State: in_progress -> completed (Req. 9.2, 9.4) ---
    final_transition = apply_diarization_event(current_state, "diarization_completed")
    utc_now = datetime.now(UTC)

    capabilities = engine.capabilities()

    # --- Build ORM entities ---
    diarization_id = str(uuid.uuid4())
    diarization = Diarization(
        id=diarization_id,
        meeting_id=meeting_id,
        transcript_id=transcript.id,
        provider=capabilities.provider_name,
        speaker_count=result.speaker_count,
        diarization_state=final_transition.new_state,  # "completed"
        failure_cause=final_transition.failure_cause,  # None on success
        created_at=utc_now,
        updated_at=utc_now,
    )

    # Map domain Speakers -> ORM, indexed by raw_label
    orm_speakers: list[Speaker] = []
    speaker_id_by_label: dict[str, str] = {}
    for speaker in domain_speakers:
        s_id = str(uuid.uuid4())
        speaker_id_by_label[speaker.raw_label] = s_id
        orm_speakers.append(
            Speaker(
                id=s_id,
                diarization_id=diarization_id,
                raw_label=speaker.raw_label,
                label=speaker.label,
                sequence=speaker.sequence,
            )
        )

    # Map domain assignments -> ORM
    orm_assignments: list[SpeakerAssignment] = []
    for turn_id, speaker in domain_assignments:
        orm_assignments.append(
            SpeakerAssignment(
                id=str(uuid.uuid4()),
                diarization_id=diarization_id,
                turn_id=turn_id,
                speaker_id=speaker_id_by_label[speaker.raw_label],
            )
        )

    # --- Persist in a single transaction (Req. 8.2) ---
    repo = DiarizationRepository(session_factory)
    async with session_factory() as session, session.begin():
        await repo.create(session, diarization, orm_speakers, orm_assignments)

    logger.info(
        "Diarization completed for meeting_id=%s (%d speakers, %d assignments)",
        meeting_id,
        len(orm_speakers),
        len(orm_assignments),
    )


async def start_worker(
    queue: JobQueue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Starts the diarization worker: subscribes to the 'diarize' topic (Req. 1.1).

    Args:
        queue: Already-connected JobQueue instance.
        session_factory: SQLAlchemy session factory for persistence.
    """

    async def handler(message: dict[str, Any]) -> None:
        await _process_diarization(message, session_factory)

    await queue.subscribe("diarize", handler)
    logger.info("Diarization worker subscribed to the 'diarize' topic")
