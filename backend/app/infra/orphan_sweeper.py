"""Resume processing that a restart or crash left without a worker, or say plainly that it failed.

A delivery normally survives a worker restart: the broker hands it to the next worker, which takes
over the lapsed claim. This sweeper is the net below that, for the cases where nothing is left to
redeliver (a lost message, a claim left by an older worker). It looks for meetings whose stage is
still open but whose claim lease lapsed, republishes that stage's message (the claim fencing makes a
duplicate harmless), backs off between tries, and after a bounded number of tries marks the meeting
failed with ``processing_interrupted`` so the owner sees an error with a retry instead of a spinner.

It never recomputes finished work: a transcription candidate has no transcript yet, a speakers
candidate has no completed revision, and nothing the owner confirmed (speakers, notes) is touched.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.repository import DiarizationRepository
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    RegenerationOperation,
    SessionRecording,
    StateHistory,
    Transcript,
)
from app.infra.processing_claims import REGENERATION_ACTIVE, lease_lapsed_at, seconds_from_env
from app.infra.queue import JobQueue
from app.meetings.service import record_transition

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 60.0
INTERRUPTED_CAUSE = "processing_interrupted"
# A lapsed claim is first left alone this long: the broker's own redelivery normally takes it over.
DEFAULT_ORPHAN_AFTER_SECONDS = 300.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 120.0
# A stage that has been open this long without finishing is given up whatever the attempts say,
# so a job that keeps killing its workers cannot loop for ever across restarts.
DEFAULT_MAX_AGE_SECONDS = 24 * 3600.0
_FORGET_AFTER_SECONDS = 24 * 3600.0
_MAX_BACKOFF_SECONDS = 1800.0


@dataclass
class _Tries:
    count: int = 0
    next_at: float = 0.0


@dataclass(frozen=True)
class _Orphan:
    stage: str  # "transcription" | "speakers"
    meeting_id: str
    generation: int
    claim_id: str | None
    opened_at: datetime
    message: dict[str, object]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OrphanSweeper:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        queue: JobQueue,
        *,
        orphan_after_s: float | None = None,
        max_attempts: int | None = None,
        backoff_s: float | None = None,
        max_age_s: float | None = None,
    ) -> None:
        self._factory = factory
        self._queue = queue
        self._orphan_after = timedelta(
            seconds=orphan_after_s if orphan_after_s is not None
            else seconds_from_env("PROCESSING_ORPHAN_AFTER_SECONDS", DEFAULT_ORPHAN_AFTER_SECONDS)
        )
        self._max_attempts = max_attempts if max_attempts is not None else int(
            seconds_from_env("PROCESSING_ORPHAN_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
        )
        self._backoff_s = backoff_s if backoff_s is not None else seconds_from_env(
            "PROCESSING_ORPHAN_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS
        )
        self._max_age = timedelta(
            seconds=max_age_s if max_age_s is not None
            else seconds_from_env("PROCESSING_ORPHAN_MAX_AGE_SECONDS", DEFAULT_MAX_AGE_SECONDS)
        )
        self._tries: dict[tuple[str, str, int], _Tries] = {}

    # --- discovery -------------------------------------------------------------------------

    async def _orphans(self, session: AsyncSession) -> list[_Orphan]:
        now = datetime.now(UTC)
        no_active_operation = ~exists().where(
            RegenerationOperation.meeting_id == Meeting.id, RegenerationOperation.status.in_(REGENERATION_ACTIVE),
        )
        found: list[_Orphan] = []

        rows = (await session.execute(
            select(Meeting, MeetingProcessingClaim, SessionRecording)
            .join(MeetingProcessingClaim, MeetingProcessingClaim.meeting_id == Meeting.id)
            .join(SessionRecording, SessionRecording.meeting_id == Meeting.id)
            .where(
                Meeting.process_state == "transcribing",
                ~exists().where(Transcript.meeting_id == Meeting.id),
                no_active_operation,
            )
        )).all()
        queued: int | None | bool = False  # looked up only if a candidate needs it
        for meeting, claim, recording in rows:
            entered = await session.scalar(
                select(func.max(StateHistory.occurred_at)).where(
                    StateHistory.meeting_id == meeting.id, StateHistory.state == "transcribing",
                )
            )
            opened_at = _utc(entered) if entered is not None else now
            if claim.claim_id is None and claim.claim_kind is None:
                # Nothing holds the stage. That is only an orphan when no message is waiting for it.
                if now - opened_at < self._orphan_after:
                    continue
                if queued is False:
                    queued = await self._queue.pending_count("transcribe")
                if queued != 0:
                    continue
            elif claim.claim_kind == "transcription":
                lapsed = await lease_lapsed_at(session, claim)
                if lapsed is None or now - lapsed < self._orphan_after:
                    continue
            else:
                continue
            found.append(_Orphan(
                "transcription", meeting.id, claim.generation, claim.claim_id, opened_at, {
                    "meeting_id": meeting.id, "owner_id": meeting.created_by, "recording_id": recording.id,
                    "audio_ref": recording.audio_ref, "generation": claim.generation,
                },
            ))

        speaker_rows = (await session.execute(
            select(Meeting, MeetingProcessingClaim, SessionRecording, Transcript)
            .join(MeetingProcessingClaim, MeetingProcessingClaim.meeting_id == Meeting.id)
            .join(SessionRecording, SessionRecording.meeting_id == Meeting.id)
            .join(Transcript, Transcript.meeting_id == Meeting.id)
            .where(
                MeetingProcessingClaim.claim_kind == "diarization",
                MeetingProcessingClaim.claim_id.is_not(None),
                ~exists().where(
                    Diarization.meeting_id == Meeting.id,
                    Diarization.diarization_state.in_(("completed", "failed", "not_reconstructible")),
                ),
                no_active_operation,
            )
        )).all()
        for meeting, claim, recording, transcript in speaker_rows:
            lapsed = await lease_lapsed_at(session, claim)
            if lapsed is None or now - lapsed < self._orphan_after:
                continue
            found.append(_Orphan(
                "speakers", meeting.id, claim.generation, claim.claim_id, _utc(transcript.created_at), {
                    "meeting_id": meeting.id, "owner_id": meeting.created_by, "recording_id": recording.id,
                    "generation": claim.generation,
                    "job_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sauri:diarize:{meeting.id}:{claim.generation}")),
                },
            ))
        return found

    # --- action ----------------------------------------------------------------------------

    async def sweep(self) -> list[str]:
        """One pass: give up on the hopeless, republish at most one stage. Returns what it did."""
        async with self._factory() as session:
            orphans = await self._orphans(session)
        now_mono = time.monotonic()
        self._tries = {
            key: tries for key, tries in self._tries.items() if now_mono - tries.next_at < _FORGET_AFTER_SECONDS
        }
        actions: list[str] = []
        republished = False
        for orphan in orphans:
            key = (orphan.stage, orphan.meeting_id, orphan.generation)
            tries = self._tries.setdefault(key, _Tries())
            too_old = datetime.now(UTC) - orphan.opened_at > self._max_age
            if too_old or tries.count >= self._max_attempts:
                if await self._give_up(orphan):
                    self._tries.pop(key, None)
                    actions.append(f"failed:{orphan.stage}:{orphan.meeting_id}")
                continue
            if republished or now_mono < tries.next_at:
                continue
            republished = True
            tries.count += 1
            tries.next_at = now_mono + min(self._backoff_s * 2 ** (tries.count - 1), _MAX_BACKOFF_SECONDS)
            topic = "transcribe" if orphan.stage == "transcription" else "diarize"
            message = dict(orphan.message)
            message.setdefault("job_id", str(uuid.uuid4()))
            try:
                await self._queue.publish(topic, message)
            except Exception:
                logger.exception("Could not republish %s for meeting_id=%s", orphan.stage, orphan.meeting_id)
                continue
            logger.warning(
                "Republished orphaned %s; meeting_id=%s attempt=%d/%d",
                orphan.stage, orphan.meeting_id, tries.count, self._max_attempts,
            )
            actions.append(f"republished:{orphan.stage}:{orphan.meeting_id}")
        return actions

    async def _give_up(self, orphan: _Orphan) -> bool:
        """Mark the open stage failed, if nothing changed since it was found. True when it did."""
        async with self._factory() as session, session.begin():
            claim = await session.scalar(
                select(MeetingProcessingClaim)
                .where(MeetingProcessingClaim.meeting_id == orphan.meeting_id).with_for_update()
            )
            meeting = await session.scalar(select(Meeting).where(Meeting.id == orphan.meeting_id).with_for_update())
            if (
                claim is None or meeting is None or claim.generation != orphan.generation
                or claim.claim_id != orphan.claim_id
            ):
                return False  # a worker took it over meanwhile
            if orphan.stage == "transcription":
                done = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting.id))
                if done is not None or meeting.process_state != "transcribing":
                    return False
                await record_transition(session, meeting, "engine_failed", failure_cause=INTERRUPTED_CAUSE)
            else:
                transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting.id))
                if transcript is None:
                    return False
                repo = DiarizationRepository(async_sessionmaker(expire_on_commit=False))  # only reserves
                attempt = await repo.reserve_next_revision(session, meeting.id, transcript.id, reuse_terminal=True)
                if attempt.diarization_state not in ("pending", "in_progress"):
                    return False
                attempt.diarization_state = "failed"
                attempt.failure_cause = INTERRUPTED_CAUSE
                attempt.updated_at = datetime.now(UTC)
        logger.error("Gave up on interrupted %s; meeting_id=%s", orphan.stage, orphan.meeting_id)
        return True


async def run_orphan_sweeper(
    factory: async_sessionmaker[AsyncSession], queue: JobQueue, interval_seconds: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Background loop of the worker."""
    sweeper = OrphanSweeper(factory, queue)
    while True:
        try:
            await sweeper.sweep()
        except Exception:
            logger.exception("Error in orphaned-processing sweep")
        await asyncio.sleep(interval_seconds)
