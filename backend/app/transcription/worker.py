"""Transcription worker — consumes the queue and produces Transcripts.

Subscribes to the "transcribe" topic of the JobQueue. For each message:
1. Creates an ASREngine via the configuration factory.
2. Invokes transcribe with the message language or configured default.
3. If there are segments -> persists Transcript + SpeechTurn -> transitions to "completed".
4. If there are no segments -> transitions to "failed" with cause "engine_failure".
5. If the engine reports no detected speech -> "failed" with cause "no_speech_detected"
   (no retry offered, no diarization, no summary).
6. A local engine that refuses the request for its one model says why: the active model's files are missing
   ("local_model_missing"), it cannot serve the language ("language_not_supported") or it failed on this
   recording ("local_model_failed"). No other model transcribes it instead; the user retries or chooses another.

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.engines.repository import apply_provenance
from app.engines.routing import (
    Provenance,
    ProviderError,
    ResolvedRoute,
    Route,
    call_with_fallback,
    resolve_route,
)
from app.infra.claim_lease import ClaimLost, LeaseScope
from app.infra.engine_slot import ENGINE_CALL_TIMEOUT_S, SLOT_WAIT_TIMEOUT_S, EngineSlotTimeout, engine_slot
from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript, TranscriptWord
from app.infra.processing_claims import (
    advance_processing_generation,
    claim_worker_generation,
    verify_worker_binding,
    verify_worker_generation,
)
from app.infra.queue import JobQueue
from app.meetings.service import record_transition
from app.regeneration import service as regeneration
from app.transcription.asr_engine import (
    ASRCapabilities,
    EngineContractError,
    TranscriptionOptions,
    TranscriptionResult,
    default_language,
)
from app.transcription.factory import create_asr_engine
from app.transcription.local_provider import LocalProvider
from app.transcription.repository import TranscriptRepository, replace_transcript_content

logger = logging.getLogger(__name__)

NO_SPEECH_CAUSE = "no_speech_detected"
# Local engine refusals (HTTP status, ``detail``) and the failure cause each one records.
LOCAL_ENGINE_CAUSES: dict[tuple[int, str], str] = {
    (422, "no_speech"): NO_SPEECH_CAUSE,
    (409, "model_not_installed"): "local_model_missing",
    (409, "model_not_verified"): "local_model_missing",
    (422, "language_not_supported"): "language_not_supported",
    (500, "model_failed"): "local_model_failed",
    (503, "model_failed"): "local_model_failed",
}


def _local_engine_cause(exc: httpx.HTTPError) -> str:
    """The failure cause of an engine HTTP error: a known refusal, else the generic ``engine_failed``."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return "engine_failed"
    try:
        body = exc.response.json()
    except ValueError:
        return "engine_failed"
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, str):
        return "engine_failed"
    return LOCAL_ENGINE_CAUSES.get((exc.response.status_code, detail), "engine_failed")


async def _publish_diarization(
    message: dict[str, Any], session_factory: async_sessionmaker[AsyncSession], queue: JobQueue,
    holder: str | None = None,
) -> bool:
    """Hand a committed transcript to diarization once; False when the fence says it already moved on.

    A delivery that does not hold the claim (the redelivery of a job whose worker died after
    committing the transcript) takes it first, once the previous lease has lapsed.
    """
    meeting_id = message["meeting_id"]
    async with session_factory() as session, session.begin():
        if not await verify_worker_binding(
            session, meeting_id=meeting_id, owner_id=message["owner_id"], recording_id=message["recording_id"],
        ):
            return False
        if holder is None:
            holder = await claim_worker_generation(
                session, meeting_id=meeting_id, generation=message.get("generation"), job_id=message.get("job_id"),
                kind="transcription", operation_id=message.get("operation_id"),
            )
        if holder is None or not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=message.get("generation"), job_id=message.get("job_id"),
            kind="transcription", operation_id=message.get("operation_id"), holder=holder,
        ):
            return False
        job = {key: message[key] for key in ("meeting_id", "owner_id", "recording_id")}
        generation = message.get("generation")
        if type(generation) is int:
            next_generation = await advance_processing_generation(session, meeting_id, generation)
            if next_generation is None:
                return False
            job.update(generation=next_generation, job_id=str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"sauri:diarize:{meeting_id}:{next_generation}",
            )))
        # Keep the generation lock until broker confirmation. Failed publication
        # rolls back advancement; redelivery finds the transcript and retries here.
        await queue.publish("diarize", job)
        return True


async def _process_transcription(
    message: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    queue: JobQueue | None = None,
) -> None:
    """Process one delivery with its claim kept alive; an interrupted one gives the claim back."""
    async with LeaseScope(session_factory) as scope:
        try:
            await _run_transcription(message, session_factory, queue, scope)
        except ClaimLost:
            logger.warning("Transcription abandoned: its processing claim was lost to another worker")


async def _run_transcription(
    message: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    queue: JobQueue | None,
    scope: LeaseScope,
) -> None:
    """Processes a message from the transcription queue.

    Args:
        message: Expected: {"meeting_id": str, "owner_id": str, "recording_id": str, "audio_ref": str}
        session_factory: Async SQLAlchemy session factory.
        queue: Optional JobQueue; if provided, once the Transcript becomes
            available a Diarization_Message is published to the "diarize"
            topic with the meeting_id (Req. 1.2 of the speaker-identification
            feature).
    """
    # --- Message validation (Req. 1.2, 1.3) ---
    meeting_id = message.get("meeting_id")
    owner_id = message.get("owner_id")
    recording_id = message.get("recording_id")
    audio_ref = message.get("audio_ref")
    generation = message.get("generation")
    job_id = message.get("job_id")
    operation_id = message.get("operation_id")

    if not meeting_id or not isinstance(meeting_id, str) or not meeting_id.strip():
        logger.warning("Message discarded: reason=missing_meeting_id")
        return

    if not owner_id or not isinstance(owner_id, str) or not owner_id.strip():
        logger.warning("Message discarded: owner_id missing or empty.")
        return

    if not recording_id or not isinstance(recording_id, str) or not recording_id.strip():
        logger.warning("Message discarded: recording_id missing or empty.")
        return

    if not audio_ref or not isinstance(audio_ref, str) or not audio_ref.strip():
        logger.warning("Message discarded: reason=missing_audio_ref")
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
            "Message discarded: Meeting not found for meeting_id=%s",
            meeting_id,
        )
        return
    if meeting.created_by != owner_id:
        logger.warning("Message discarded: queue owner does not match meeting owner.")
        return
    if recording is None or recording.id != recording_id:
        logger.warning("Message discarded: queue recording does not match meeting recording.")
        return

    async with session_factory() as session:
        persisted_transcript = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id))
        # Only an explicit, live regeneration operation may compute a finished stage again.
        regenerating = await regeneration.is_live_operation(session, operation_id, "transcription")
    if persisted_transcript is not None and not regenerating:
        published = queue is not None and await _publish_diarization(message, session_factory, queue)
        if not published:
            logger.info("Transcription delivery dropped; reason=stage_complete")
        return
    if operation_id is None and meeting.process_state in ("completed", "failed"):
        # A settled meeting never starts transcription from an ordinary message.
        logger.info("Transcription delivery dropped; reason=meeting_settled")
        return

    async with session_factory() as session, session.begin():
        holder = await claim_worker_generation(
            session, meeting_id=meeting_id, generation=generation, job_id=job_id,
            kind="transcription", operation_id=operation_id,
        )
    if holder is None:
        logger.info("Transcription delivery acknowledged without claim; reason=fenced")
        return
    scope.arm(meeting_id=meeting_id, generation=generation, holder=holder, kind="transcription",
              operation_id=operation_id)

    async with session_factory() as session, session.begin():
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None or not await verify_worker_binding(
            session, meeting_id=meeting_id, owner_id=owner_id, recording_id=recording_id,
        ) or not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=generation, job_id=job_id,
            kind="transcription", operation_id=operation_id, holder=holder,
        ):
            return
        if regenerating:
            live = await regeneration.locked_active_operation(session, operation_id, "transcription")
            if live is None:
                return
            await regeneration.mark_running(session, live)
        elif meeting.process_state == "recording":
            await record_transition(session, meeting, "recording_uploaded")

    logger.info("Processing transcription for meeting_id=%s", meeting_id)
    recording_audio_ref = recording.audio_ref
    audio_duration_seconds = recording.duration_seconds

    # 1. Create the ASR engine via the factory (selects provider by config)
    engine = create_asr_engine()

    # 2. Transcribe only the audio persisted for this meeting. The queue's
    # audio_ref is untrusted and must not select the object sent to the engine.
    options = TranscriptionOptions()
    if message.get("language"):
        options.preferred_language = message["language"]
    started_at = time.monotonic()
    provenance = Provenance(None, None, external=False)
    try:
        resolved = ResolvedRoute(None)
        if isinstance(engine, LocalProvider):
            # Per attempt, so a change in Settings applies to the next one without restarting anything.
            async with session_factory() as session:
                resolved = await resolve_route(session, owner_id, "transcription")

        async def attempt(route: Route | None) -> TranscriptionResult:
            # No route means the plain call of every run before engines were selectable.
            return await engine.transcribe(
                recording_audio_ref, options if route is None else replace(options, route=route)
            )

        async def run_engine() -> tuple[TranscriptionResult, Provenance]:
            async with engine_slot(session_factory.kw["bind"], kind="transcription", timeout_s=SLOT_WAIT_TIMEOUT_S):
                async with asyncio.timeout(ENGINE_CALL_TIMEOUT_S):
                    return await call_with_fallback(resolved, attempt, _engine_names)

        result, provenance = await scope.guard(run_engine())
        if type(result.contract_version) is not int or result.contract_version != 2:
            raise EngineContractError("Unsupported ASR contract_version")
        if result.language == "auto":
            raise EngineContractError("Missing detected language")
        if not result.language:
            if options.preferred_language == "auto":
                raise EngineContractError("Missing detected language")
            result.language = options.preferred_language
    except EngineSlotTimeout:
        # Not an engine failure: the scope gives the claim back and the queue offers the job again.
        raise
    except (httpx.HTTPError, ValueError, TimeoutError, ProviderError) as exc:
        if isinstance(exc, ProviderError):
            cause = exc.code  # a closed class code: what failed, never what was said
        elif isinstance(exc, EngineContractError):
            cause = "engine_contract_mismatch"
        elif isinstance(exc, TimeoutError):
            cause = "engine_timeout"
        elif isinstance(exc, httpx.HTTPError):
            cause = _local_engine_cause(exc)
        else:
            cause = "invalid_response"
        elapsed_seconds = time.monotonic() - started_at
        async with session_factory() as session, session.begin():
            meeting = await session.get(Meeting, meeting_id)
            if (
                meeting is not None
                and await verify_worker_binding(
                    session, meeting_id=meeting_id, owner_id=owner_id, recording_id=recording_id
                )
                and await verify_worker_generation(
                    session, meeting_id=meeting_id, generation=generation, job_id=job_id,
                    kind="transcription", operation_id=operation_id, holder=holder,
                )
            ):
                live = (
                    await regeneration.locked_active_operation(session, operation_id, "transcription")
                    if regenerating else None
                )
                if live is not None:
                    # The previous transcript, speakers and summary stay usable.
                    await regeneration.fail_operation(session, live, cause)
                else:
                    if meeting.process_state == "recording":
                        await record_transition(session, meeting, "recording_uploaded")
                    await record_transition(session, meeting, "engine_failed", failure_cause=cause)
        if cause == NO_SPEECH_CAUSE:
            # An expected outcome: retrying the same audio cannot produce text.
            logger.info(
                "No speech detected for meeting_id=%s; cause=%s; elapsed_seconds=%.2f",
                meeting_id, cause, elapsed_seconds,
            )
            return
        logger.error(
            "Transcription failed for meeting_id=%s; cause=%s; "
            "elapsed_seconds=%.2f; manual retry available",
            meeting_id,
            cause,
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
    follow_up: regeneration.Dispatch | None = None
    async with session_factory() as session, session.begin():
        # Re-fetch meeting within the transaction for state transitions
        meeting = await session.get(Meeting, meeting_id)
        if (
            meeting is None
            or not await verify_worker_binding(
                session, meeting_id=meeting_id, owner_id=owner_id, recording_id=recording_id
            )
            or not await verify_worker_generation(
                session, meeting_id=meeting_id, generation=generation, job_id=job_id,
                kind="transcription", operation_id=operation_id, holder=holder,
            )
        ):
            logger.info("Transcription artifact write skipped; reason=fenced")
            return

        if regenerating:
            follow_up = await _settle_regeneration(
                session, meeting, operation_id, result, engine.capabilities(), provenance,
            )
        elif result.segments:
            # Text was produced -> persist Transcript and turns (Req. 3.4, 3.5)
            capabilities = engine.capabilities()
            provenance = _with_capabilities(provenance, capabilities)

            transcript = Transcript(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                language=result.language,
                provider="local" if capabilities.is_local and not provenance.external else "cloud",
                supports_turns=capabilities.supports_turns,
                expires_at=None,
                created_at=datetime.now(UTC),
            )
            apply_provenance(transcript, provenance)

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
            session.add_all([
                TranscriptWord(
                    id=str(uuid.uuid4()), transcript_id=transcript.id, sequence=sequence,
                    text=word.text, start_ms=word.start_ms, end_ms=word.end_ms,
                    probability=word.probability, timing_repaired=word.timing_repaired,
                )
                for sequence, word in enumerate(result.words, start=1)
            ])
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

    if queue is not None and transcript_created:
        await _publish_diarization(message, session_factory, queue, holder)
    if follow_up is not None and queue is not None:
        # The cascade continues with speakers, one turn at a time through the engine slot.
        try:
            await queue.publish(follow_up.topic, follow_up.message)
        except Exception:
            logger.error("Cascade publication failed for meeting_id=%s", meeting_id)
            await regeneration.fail_unpublished(session_factory, follow_up)


def _with_capabilities(provenance: Provenance, capabilities: ASRCapabilities) -> Provenance:
    """An engine that is not local (the legacy cloud provider) sent the audio out whatever the route said."""
    return provenance if capabilities.is_local else replace(provenance, external=True)


def _engine_names(result: TranscriptionResult) -> tuple[str | None, str | None]:
    """What the engine reported about itself (None for engines that do not say)."""
    return (result.engine.name, result.engine.model) if result.engine is not None else (None, None)


async def _settle_regeneration(
    session: AsyncSession, meeting: Meeting, operation_id: Any, result: TranscriptionResult,
    capabilities: ASRCapabilities, provenance: Provenance,
) -> regeneration.Dispatch | None:
    """Commit a regenerated transcript, or fail the operation, in the verified transaction."""
    live = await regeneration.locked_active_operation(session, operation_id, "transcription")
    if live is None:
        return None
    if not result.segments:
        await regeneration.fail_operation(session, live, "engine_failure")
        return None
    now = datetime.now(UTC)
    provenance = _with_capabilities(provenance, capabilities)
    provider = "local" if capabilities.is_local and not provenance.external else "cloud"
    transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting.id))
    if transcript is None:
        # A failed meeting retried explicitly has no transcript to replace.
        transcript = Transcript(
            id=str(uuid.uuid4()), meeting_id=meeting.id, language=result.language, provider=provider,
            supports_turns=capabilities.supports_turns, expires_at=None, created_at=now,
        )
        apply_provenance(transcript, provenance)
        session.add(transcript)
        await session.flush()
    await replace_transcript_content(
        session, transcript, language=result.language, provider=provider,
        supports_turns=capabilities.supports_turns, segments=result.segments, words=result.words, now=now,
        provenance=provenance,
    )
    transition = await record_transition(session, meeting, "transcription_completed")
    if transition.successful:
        meeting.failure_cause = None
    await regeneration.succeed_operation(session, live, finished_at=now)
    return await regeneration.follow_up(session, live)


async def start_worker(
    queue: JobQueue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Starts the transcription worker: subscribes to the 'transcribe' topic.

    Args:
        queue: Already-connected JobQueue instance.
        session_factory: SQLAlchemy session factory for persistence.
    """

    default_language()  # Reject invalid configuration before subscribing to the queue.

    async def handler(message: dict[str, Any]) -> None:
        await _process_transcription(message, session_factory, queue)

    async def terminal(message: dict[str, Any]) -> None:
        meeting_id = message.get("meeting_id")
        if not isinstance(meeting_id, str):
            return
        async with session_factory() as session, session.begin():
            live = await regeneration.locked_active_operation(session, message.get("operation_id"), "transcription")
            if live is not None and live.meeting_id == meeting_id:
                # Exhausted retries of an explicit run: fail it and keep the previous outputs.
                await regeneration.fail_operation(session, live, "processing_retries_exhausted")
                return
        async with session_factory() as session:
            transcript = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id))
        if transcript is not None:
            # Exhausted publication retries must still deliver the already committed result.
            await _publish_diarization(message, session_factory, queue)
            return
        async with session_factory() as session, session.begin():
            if not await verify_worker_binding(
                session, meeting_id=meeting_id, owner_id=message.get("owner_id", ""),
                recording_id=message.get("recording_id", ""),
            ):
                return
            binding: dict[str, Any] = {
                "meeting_id": meeting_id, "generation": message.get("generation"),
                "job_id": message.get("job_id"), "operation_id": message.get("operation_id"),
            }
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None or meeting.process_state != "transcribing":
                return  # already settled: a repeated terminal delivery must not wait on the first one's claim
            if await claim_worker_generation(session, kind="transcription", **binding) is None:
                return
            await record_transition(session, meeting, "engine_failed", failure_cause="processing_retries_exhausted")

    await queue.subscribe("transcribe", handler)
    await queue.subscribe("transcribe.failed", terminal)
    logger.info("Transcription worker subscribed to the 'transcribe' topic")
