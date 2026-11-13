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
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import DiarizationOptions
from app.diarization.factory import create_diarization_engine
from app.diarization.labeling import label_speakers
from app.diarization.presentation import PreparedResult, validate_prepared
from app.diarization.repository import DiarizationRepository
from app.diarization.reprocess_legacy import expired
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
)
from app.infra.object_store import create_object_store
from app.infra.processing_claims import (
    claim_worker_generation,
    verify_worker_binding,
    verify_worker_generation,
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
        message: Expected: {"meeting_id": str, "owner_id": str, "recording_id": str}
        session_factory: Async SQLAlchemy session factory.
    """
    # --- Message validation (Req. 1.3, 1.4) ---
    meeting_id = message.get("meeting_id")
    owner_id = message.get("owner_id")
    recording_id = message.get("recording_id")
    generation = message.get("generation")
    job_id = message.get("job_id")
    operation_id = message.get("operation_id")
    if not meeting_id or not isinstance(meeting_id, str) or not meeting_id.strip():
        logger.warning("Diarization message discarded: reason=missing_meeting_id")
        return
    revision = message.get("processing_revision")
    if revision is not None and (type(revision) is not int or revision < 1):
        logger.warning("Diarization discarded: invalid processing_revision")
        return
    if revision is None and (
        not isinstance(owner_id, str) or not owner_id.strip()
        or not isinstance(recording_id, str) or not recording_id.strip()
    ):
        logger.warning("Diarization message discarded: missing owner or recording binding")
        return

    # Bind the job to the persisted meeting owner and its exact recording.
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        recording = (
            await session.execute(
                select(SessionRecording).where(
                    SessionRecording.meeting_id == meeting_id
                )
            )
        ).scalar_one_or_none()
    if meeting is None:
        logger.warning(
            "Diarization discarded: Meeting not found for meeting_id=%s",
            meeting_id,
        )
        return
    if owner_id is not None and meeting.created_by != owner_id:
        logger.warning("Diarization discarded: queue owner does not match meeting owner.")
        return
    if recording is None or (recording_id is not None and recording.id != recording_id):
        logger.warning("Diarization discarded: queue recording does not match meeting recording.")
        return
    # A reserved revision is itself the durable job binding; its publication
    # carries only meeting/revision, never owner or audio references.
    owner_id, recording_id = meeting.created_by, recording.id

    # Ordinary capture jobs retain their existing processing-generation fence.
    # Backfill deliveries are already fenced by the persisted revision claim.
    has_processing_fence = revision is None or any(
        value is not None for value in (generation, job_id, operation_id)
    )
    if has_processing_fence:
        async with session_factory() as session, session.begin():
            if not await claim_worker_generation(
                session, meeting_id=meeting_id, generation=generation, job_id=job_id,
                kind="diarization", operation_id=operation_id,
            ):
                logger.info("Diarization delivery acknowledged without claim; reason=fenced")
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

    repo = DiarizationRepository(session_factory)
    if revision is None:
        # Ordinary transcription jobs have no revision yet. The persisted reservation
        # precedes the engine call, even when this is their first generation.
        async with session_factory() as session, session.begin():
            attempt = await repo.reserve_next_revision(
                session, meeting_id, transcript.id, reuse_terminal=True,
            )
            revision = attempt.processing_revision
    else:
        # Published jobs must match the reserved transcript and may not manufacture
        # an attempt for an arbitrary revision supplied in a queue message.
        async with session_factory() as session:
            reserved: Diarization | None = await session.scalar(select(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == revision,
                Diarization.transcript_id == transcript.id,
            ))
            if reserved is None:
                logger.warning("Diarization discarded: unreserved revision")
                return
            attempt = reserved
    if message.get("processing_revision") is not None:
        # A queue message is not an audio capability. Rebind its persisted exact
        # object under the meeting lock, and fail closed before engine creation.
        async with session_factory() as session, session.begin():
            await session.scalar(select(Meeting).where(Meeting.id == meeting_id).with_for_update())
            current = await session.scalar(select(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == revision,
                Diarization.transcript_id == transcript.id,
                Diarization.diarization_state == "pending",
            ))
            current_transcript = await session.get(type(transcript), transcript.id)
            current_recording = await session.scalar(select(SessionRecording).where(
                SessionRecording.meeting_id == meeting_id,
            ))
            if current is None or current_transcript is None or expired(
                current_transcript.expires_at, datetime.now(UTC)
            ) or current_recording is None or current_recording.id != recording_id or not current_recording.audio_ref:
                logger.info("Diarization revision skipped; reason=ineligible_or_not_pending")
                return
            unavailable = expired(current_recording.expires_at, datetime.now(UTC))
            if not unavailable:
                availability = await create_object_store().inspect(current_recording.audio_ref)
                if availability not in {"available", "missing"}:
                    raise ValueError("object availability response is invalid")
                unavailable = availability == "missing"
            if unavailable:
                await repo.reserve_next_revision(
                    session, meeting_id, transcript.id, audio_unavailable=True,
                )
                logger.info("Diarization revision terminal; reason=audio_unavailable")
                return
            # Use the revalidated reference, never an alternative from the message.
            recording = current_recording
            if not await repo.claim_revision(session, meeting_id, revision):
                return
    else:
        async with session_factory() as session, session.begin():
            if not await repo.claim_revision(session, meeting_id, revision):
                logger.info("Diarization delivery acknowledged without claim; reason=revision_not_pending")
                return

    try:
        if attempt.prepared_result is not None:
            prepared = PreparedResult.model_validate(attempt.prepared_result)
            validate_prepared(prepared, list(transcript.turns),
                                transcript_id=transcript.id, diarization_id=attempt.id, revision=revision)
            orm_speakers = [Speaker(diarization_id=attempt.id, **s.model_dump()) for s in prepared.speakers]
            orm_assignments = [SpeakerAssignment(diarization_id=attempt.id, **a.model_dump())
                               for a in prepared.assignments]
            provider = prepared.provider
        else:
            engine = create_diarization_engine()
            result = await engine.diarize(
                recording.audio_ref, DiarizationOptions(duration_ms=recording.duration_seconds * 1000)
            )
            domain_speakers = label_speakers(result.segments)
            domain_assignments = assign_turns(
                list(transcript.turns), result.segments, domain_speakers,
                require_exclusive=os.environ.get("DIARIZATION_EXCLUSIVE_ASSIGNMENTS", "0") == "1",
            )
            speaker_id_by_label: dict[str, str] = {}
            orm_speakers = []
            for speaker in domain_speakers:
                speaker_id = str(uuid.uuid4())
                speaker_id_by_label[speaker.raw_label] = speaker_id
                orm_speakers.append(Speaker(
                    id=speaker_id, diarization_id=attempt.id, raw_label=speaker.raw_label,
                    label=speaker.label, sequence=speaker.sequence,
                ))
            orm_assignments = [SpeakerAssignment(
                id=str(uuid.uuid4()), diarization_id=attempt.id, turn_id=turn_id,
                speaker_id=speaker_id_by_label[speaker.raw_label], overlap_ms=overlap_ms,
            ) for turn_id, speaker, overlap_ms in domain_assignments]
            provider = engine.capabilities().provider_name

        async with session_factory() as session, session.begin():
            if (
                not await verify_worker_binding(
                    session, meeting_id=meeting_id, owner_id=owner_id, recording_id=recording_id
                )
                or (has_processing_fence and not await verify_worker_generation(
                    session, meeting_id=meeting_id, generation=generation, job_id=job_id,
                    kind="diarization", operation_id=operation_id,
                ))
            ):
                logger.info("Diarization artifact write skipped; reason=fenced")
                return
            await repo.complete_revision(
                session, meeting_id, revision, provider,
                orm_speakers, orm_assignments,
            )
    except Exception:
        async with session_factory() as session, session.begin():
            await repo.fail_revision(session, meeting_id, revision)
        raise

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
