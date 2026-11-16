"""Explicit stage regeneration: the only way a completed stage is computed again (#1053).

Automatic triggers never re-run a stage whose output exists. A user's explicit request
creates one ``RegenerationOperation``; its claim, its revision or its summary request is
what authorizes the worker to run, and every other delivery is dropped by the workers.

The caller owns the transaction. Publication to the broker happens after commit.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.repository import DiarizationRepository
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingSummary,
    RegenerationOperation,
    SessionRecording,
    StateHistory,
    SummaryRequestOutbox,
)
from app.infra.object_store import ObjectStore
from app.infra.processing_claims import REGENERATION_ACTIVE, lease_lapsed_at
from app.meetings.service import record_transition
from app.meetings.state_machine import TERMINAL_STATES
from app.summaries import repository as summary_repository
from app.summaries.service import accept_request
from app.summaries.sweeper import stale_after_seconds

logger = logging.getLogger(__name__)

Stage = Literal["transcription", "speakers", "summary"]
STAGE_ORDER: tuple[Stage, ...] = ("transcription", "speakers", "summary")
STALE_CAUSE = "stale_operation"
QUEUE_CAUSE = "queue_unavailable"


@dataclass(frozen=True)
class Dispatch:
    """One broker message to publish once the accepting transaction has committed."""

    topic: str
    message: dict[str, Any]


@dataclass(frozen=True)
class Accepted:
    operation: RegenerationOperation
    dispatch: Dispatch | None
    replay: bool = False


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def idempotency_digest(key: str) -> str:
    """Store a digest, never the caller's raw key."""
    return hashlib.sha256(key.encode()).hexdigest()


def _conflict(code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=409, detail=jsonable_encoder({"code": code, **extra}))


def downstream(stage: Stage) -> tuple[Stage, ...]:
    return STAGE_ORDER[STAGE_ORDER.index(stage) + 1:]


def replaces_for(stage: Stage, cascade: bool) -> list[str]:
    return [stage, *downstream(stage)] if cascade else [stage]


# --- Reading -----------------------------------------------------------------------


async def active_operation(session: AsyncSession, meeting_id: str) -> RegenerationOperation | None:
    return await session.scalar(
        select(RegenerationOperation)
        .where(RegenerationOperation.meeting_id == meeting_id, RegenerationOperation.status.in_(REGENERATION_ACTIVE))
        .order_by(RegenerationOperation.requested_at.desc())
        .limit(1)
    )


async def latest_operation(session: AsyncSession, meeting_id: str) -> RegenerationOperation | None:
    return await session.scalar(
        select(RegenerationOperation)
        .where(RegenerationOperation.meeting_id == meeting_id)
        .order_by(RegenerationOperation.requested_at.desc(), RegenerationOperation.id.desc())
        .limit(1)
    )


async def locked_any_operation(session: AsyncSession, operation_id: str) -> RegenerationOperation | None:
    return await session.scalar(
        select(RegenerationOperation).where(RegenerationOperation.id == operation_id).with_for_update()
    )


async def operation_for_meeting(
    session: AsyncSession, meeting_id: str, operation_id: str
) -> RegenerationOperation | None:
    return await session.scalar(
        select(RegenerationOperation).where(
            RegenerationOperation.id == operation_id, RegenerationOperation.meeting_id == meeting_id
        )
    )


async def operation_view(session: AsyncSession, op: RegenerationOperation) -> dict[str, Any]:
    """Wire form of an operation; a summary run reports its request's live progress."""
    status, started_at, finished_at, cause = op.status, op.started_at, op.finished_at, op.failure_cause
    if op.stage == "summary" and op.summary_event_id is not None and status in REGENERATION_ACTIVE:
        request = await session.get(SummaryRequestOutbox, op.summary_event_id)
        if request is not None and request.status == "running":
            status, started_at = "running", request.started_at
    next_id = await session.scalar(
        select(RegenerationOperation.id).where(RegenerationOperation.parent_operation_id == op.id).limit(1)
    )
    details = dict(op.details or {})
    view: dict[str, Any] = {
        "operation_id": op.id,
        "meeting_id": op.meeting_id,
        "stage": op.stage,
        "status": status,
        "cascade": op.cascade,
        "requested_at": utc(op.requested_at),
        "started_at": utc(started_at),
        "finished_at": utc(finished_at),
        "failure_cause": cause,
        "replaces": details.pop("replaces", [op.stage]),
        "stale": details.pop("stale", []),
        "parent_operation_id": op.parent_operation_id,
        "next_operation_id": next_id,
        "summary_request_id": op.summary_event_id,
        "details": details or None,
    }
    return view


async def meeting_hints(session: AsyncSession, meeting_id: str) -> dict[str, Any]:
    """Optional meeting-detail additions: stale stages and the active operation.

    Staleness comes only from succeeded operations: a stage is stale when the stage
    upstream of it was explicitly regenerated after its own output was produced.
    """
    hints: dict[str, Any] = {}
    stale = await stale_stages(session, meeting_id)
    if stale:
        hints["stale_stages"] = stale
    active = await active_operation(session, meeting_id)
    if active is not None:
        view = await operation_view(session, active)
        hints["active_operation"] = {
            key: view[key] for key in ("operation_id", "stage", "status", "requested_at", "started_at")
        }
    return hints


async def stale_stages(session: AsyncSession, meeting_id: str) -> list[str]:
    finished = {
        stage: [utc(value) for value in values]
        for stage, values in (await _succeeded_finish_times(session, meeting_id)).items()
    }
    result: list[str] = []
    diarized_at = utc(await session.scalar(
        select(func.max(Diarization.updated_at)).where(
            Diarization.meeting_id == meeting_id, Diarization.diarization_state == "completed"
        )
    ))
    if diarized_at is not None and any(at is not None and at > diarized_at for at in finished["transcription"]):
        result.append("speakers")
    summarized_at = utc(await session.scalar(
        select(func.max(MeetingSummary.created_at)).where(MeetingSummary.meeting_id == meeting_id)
    ))
    upstream = [*finished["transcription"], *finished["speakers"]]
    if summarized_at is not None and any(at is not None and at > summarized_at for at in upstream):
        result.append("summary")
    return result


async def _succeeded_finish_times(session: AsyncSession, meeting_id: str) -> dict[str, list[datetime | None]]:
    rows = (await session.execute(
        select(RegenerationOperation.stage, RegenerationOperation.finished_at).where(
            RegenerationOperation.meeting_id == meeting_id, RegenerationOperation.status == "succeeded"
        )
    )).all()
    grouped: dict[str, list[datetime | None]] = {"transcription": [], "speakers": [], "summary": []}
    for stage, finished_at in rows:
        grouped[stage].append(finished_at)
    return grouped


# --- Accepting a request -------------------------------------------------------------


async def _busy_reason(session: AsyncSession, meeting: Meeting, transcript_id: str | None) -> str | None:
    """The original pipeline (or a stuck run) that still owns this meeting, if any.

    A worker that holds the stage's claim owns it for as long as its lease is live, and loses it the
    moment the lease lapses, so a crashed worker frees the owner to regenerate right away. A stage
    nobody holds yet (waiting in the queue) counts as busy until it is older than the stale threshold.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds())
    claim = await session.get(MeetingProcessingClaim, meeting.id)

    async def lease(kind: str) -> bool | None:
        """True while a worker holds this kind of claim live, False once it lapsed, None without a holder."""
        if claim is None or claim.claim_kind != kind or claim.claim_id is None:
            return None
        return await lease_lapsed_at(session, claim) is None

    if meeting.process_state not in TERMINAL_STATES:
        held = await lease("transcription")
        entered = utc(await session.scalar(
            select(func.max(StateHistory.occurred_at)).where(
                StateHistory.meeting_id == meeting.id, StateHistory.state == meeting.process_state
            )
        ))
        if held or (held is None and (entered is None or entered > cutoff)):
            return "transcription"
    running = (await session.scalars(
        select(Diarization.updated_at).where(
            Diarization.meeting_id == meeting.id, Diarization.diarization_state.in_(("pending", "in_progress"))
        )
    )).all()
    held = await lease("diarization")
    if running and (held or (held is None and any((utc(at) or cutoff) > cutoff for at in running))):
        return "speakers"
    if transcript_id is not None and await summary_repository.active_request(session, transcript_id) is not None:
        return "summary"
    return None


async def _retire_abandoned_revisions(session: AsyncSession, meeting_id: str) -> None:
    await session.execute(
        update(Diarization)
        .where(Diarization.meeting_id == meeting_id, Diarization.diarization_state.in_(("pending", "in_progress")))
        .values(diarization_state="failed", failure_cause=STALE_CAUSE, updated_at=datetime.now(UTC))
    )


async def _arm_claim(session: AsyncSession, meeting_id: str, operation_id: str) -> int:
    """Open a fresh processing generation owned by this operation.

    Any older message of an earlier generation is fenced out from now on.
    """
    claim = await session.scalar(
        select(MeetingProcessingClaim).where(MeetingProcessingClaim.meeting_id == meeting_id).with_for_update()
    )
    if claim is None:
        claim = MeetingProcessingClaim(meeting_id=meeting_id, generation=1)
        session.add(claim)
    else:
        claim.generation += 1
    claim.claim_id, claim.claim_kind, claim.claim_expires_at = operation_id, "recovery", None
    await session.flush()
    return claim.generation


async def _check_media(session: AsyncSession, store: ObjectStore, meeting_id: str) -> SessionRecording:
    recording = await session.scalar(select(SessionRecording).where(SessionRecording.meeting_id == meeting_id))
    if recording is None or not recording.audio_ref:
        raise _conflict("media_unavailable")
    expires_at = utc(recording.expires_at)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise _conflict("media_unavailable")
    try:
        availability = await store.inspect(recording.audio_ref)
    except Exception as exc:
        logger.warning("Could not inspect the stored recording for meeting_id=%s", meeting_id)
        raise HTTPException(status_code=503, detail={"code": "storage_unavailable"}) from exc
    if availability != "available":
        raise _conflict("media_unavailable")
    return recording


async def request_regeneration(
    session: AsyncSession,
    store: ObjectStore,
    *,
    meeting_id: str,
    owner_id: str,
    stage: Stage,
    template_id: str | None,
    cascade: bool,
    idempotency_key: str | None,
) -> Accepted:
    meeting = await summary_repository.owned_meeting_locked(session, meeting_id, owner_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    digest = idempotency_digest(idempotency_key) if idempotency_key else None
    if digest is not None:
        previous = await session.scalar(
            select(RegenerationOperation).where(
                RegenerationOperation.requested_by == owner_id,
                RegenerationOperation.meeting_id == meeting_id,
                RegenerationOperation.idempotency_key == digest,
            )
        )
        if previous is not None:
            if (previous.stage, previous.cascade, previous.template_id) != (stage, cascade, template_id):
                raise _conflict("idempotency_key_reused")
            return Accepted(previous, None, replay=True)

    transcript = await summary_repository.transcript_for_meeting(session, meeting_id)
    active = await active_operation(session, meeting_id)
    if active is not None:
        raise _conflict("operation_active", operation=await operation_view(session, active))
    busy = await _busy_reason(session, meeting, transcript.id if transcript is not None else None)
    if busy is not None:
        raise _conflict("processing_active", active_stage=busy)
    if stage != "transcription" and transcript is None:
        raise _conflict("transcript_unavailable")
    # Fail at acceptance, not hours later in a worker, when the template is not usable.
    if template_id is not None and await summary_repository.selected_template(session, owner_id, template_id) is None:
        raise HTTPException(status_code=422, detail="Invalid template_id")
    if stage != "summary":
        await _check_media(session, store, meeting_id)

    has_speakers = await session.scalar(
        select(func.count()).select_from(Diarization).where(
            Diarization.meeting_id == meeting_id, Diarization.diarization_state == "completed"
        )
    )
    has_summary = await session.scalar(
        select(func.count()).select_from(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
    )
    existing = {"transcription": transcript is not None, "speakers": bool(has_speakers), "summary": bool(has_summary)}
    stale = [] if cascade else [name for name in downstream(stage) if existing[name]]

    now = datetime.now(UTC)
    operation = RegenerationOperation(
        id=str(uuid.uuid4()), meeting_id=meeting_id, stage=stage, status="accepted", requested_by=owner_id,
        idempotency_key=digest, cascade=cascade, template_id=template_id, requested_at=now,
        details={"replaces": replaces_for(stage, cascade), "stale": stale},
    )
    session.add(operation)
    await session.flush()
    await _retire_abandoned_revisions(session, meeting_id)

    dispatch: Dispatch | None = None
    if stage == "transcription":
        dispatch = await _begin_transcription(session, meeting, operation)
    elif stage == "speakers":
        assert transcript is not None
        dispatch = await _begin_speakers(session, meeting, operation, transcript.id)
    else:
        row = await accept_request(session, meeting_id, owner_id, template_id)
        operation.summary_event_id = row.event_id
        await session.flush()
    return Accepted(operation, dispatch)


async def _begin_transcription(session: AsyncSession, meeting: Meeting, op: RegenerationOperation) -> Dispatch:
    recording = await session.scalar(select(SessionRecording).where(SessionRecording.meeting_id == meeting.id))
    assert recording is not None
    if meeting.process_state in TERMINAL_STATES:
        # A stuck run is already "transcribing"; only a finished meeting is re-opened.
        await record_transition(session, meeting, "regeneration_started")
    op.processing_generation = await _arm_claim(session, meeting.id, op.id)
    return Dispatch("transcribe", {
        "meeting_id": meeting.id, "owner_id": meeting.created_by, "recording_id": recording.id,
        "audio_ref": recording.audio_ref, "generation": op.processing_generation,
        "job_id": str(uuid.uuid4()), "operation_id": op.id,
    })


async def _begin_speakers(
    session: AsyncSession, meeting: Meeting, op: RegenerationOperation, transcript_id: str
) -> Dispatch:
    repo = DiarizationRepository(async_sessionmaker(expire_on_commit=False))  # only reserves; opens no sessions
    attempt = await repo.reserve_next_revision(session, meeting.id, transcript_id)
    op.diarization_revision = attempt.processing_revision
    op.processing_generation = await _arm_claim(session, meeting.id, op.id)
    return Dispatch("diarize", {
        "meeting_id": meeting.id, "processing_revision": attempt.processing_revision,
        "generation": op.processing_generation, "operation_id": op.id,
    })


# --- Settling (called by workers inside their own verified transaction) ----------------


async def locked_active_operation(
    session: AsyncSession, operation_id: object, stage: Stage
) -> RegenerationOperation | None:
    """The live regeneration operation named by a message, or None for any other delivery."""
    if not isinstance(operation_id, str) or not operation_id:
        return None
    return await session.scalar(
        select(RegenerationOperation).where(
            RegenerationOperation.id == operation_id,
            RegenerationOperation.stage == stage,
            RegenerationOperation.status.in_(REGENERATION_ACTIVE),
        ).with_for_update()
    )


async def is_live_operation(session: AsyncSession, operation_id: object, stage: Stage) -> bool:
    """Read-only check that a message names a live regeneration operation of this stage."""
    if not isinstance(operation_id, str) or not operation_id:
        return False
    return await session.scalar(
        select(RegenerationOperation.id).where(
            RegenerationOperation.id == operation_id,
            RegenerationOperation.stage == stage,
            RegenerationOperation.status.in_(REGENERATION_ACTIVE),
        )
    ) is not None


async def fail_unpublished(factory: async_sessionmaker[AsyncSession], dispatch: Dispatch) -> None:
    """A follow-up whose message could not be published must not keep the meeting blocked."""
    async with factory() as session, session.begin():
        op = await locked_any_operation(session, str(dispatch.message["operation_id"]))
        if op is not None and op.status in REGENERATION_ACTIVE:
            await fail_operation(session, op, QUEUE_CAUSE)


async def mark_running(session: AsyncSession, op: RegenerationOperation) -> None:
    if op.status == "accepted":
        op.status = "running"
        op.started_at = datetime.now(UTC)
        await session.flush()


async def succeed_operation(
    session: AsyncSession, op: RegenerationOperation, *, details: dict[str, object] | None = None,
    finished_at: datetime | None = None,
) -> None:
    op.status = "succeeded"
    op.failure_cause = None
    op.finished_at = finished_at or datetime.now(UTC)
    if op.started_at is None:
        op.started_at = op.finished_at
    if details:
        op.details = {**(op.details or {}), **details}
    await session.flush()


async def fail_operation(session: AsyncSession, op: RegenerationOperation, cause: str) -> None:
    """Record the failure and give back what the run held. Previous outputs are never touched."""
    op.status = "failed"
    op.failure_cause = cause
    op.finished_at = datetime.now(UTC)
    await session.flush()
    meeting = await session.get(Meeting, op.meeting_id)
    if op.stage == "transcription" and meeting is not None and meeting.process_state == "transcribing":
        has_transcript = await summary_repository.transcript_for_meeting(session, op.meeting_id) is not None
        if has_transcript:
            await record_transition(session, meeting, "regeneration_failed")
        else:
            await record_transition(session, meeting, "engine_failed", failure_cause=cause)
    elif op.stage == "speakers" and op.diarization_revision is not None:
        await session.execute(
            update(Diarization)
            .where(
                Diarization.meeting_id == op.meeting_id,
                Diarization.processing_revision == op.diarization_revision,
                Diarization.diarization_state.in_(("pending", "in_progress")),
            )
            .values(diarization_state="failed", failure_cause=cause[:64], updated_at=datetime.now(UTC))
        )
    logger.info("Regeneration failed; stage=%s cause=%s meeting_id=%s", op.stage, cause, op.meeting_id)


async def follow_up(session: AsyncSession, parent: RegenerationOperation) -> Dispatch | None:
    """Chain the next stage of a cascade; never runs for a request without cascade.

    The parent must already be settled as succeeded and flushed, so that the one-active
    rule lets the next operation in.
    """
    if not parent.cascade:
        return None
    later = downstream(cast(Stage, parent.stage))
    if not later:
        return None
    next_stage = later[0]
    meeting = await session.get(Meeting, parent.meeting_id)
    transcript = await summary_repository.transcript_for_meeting(session, parent.meeting_id)
    assert meeting is not None and transcript is not None
    child = RegenerationOperation(
        id=str(uuid.uuid4()), meeting_id=parent.meeting_id, stage=next_stage, status="accepted",
        requested_by=parent.requested_by, idempotency_key=None, cascade=True, template_id=parent.template_id,
        parent_operation_id=parent.id, requested_at=datetime.now(UTC),
        details={"replaces": replaces_for(next_stage, True), "stale": []},
    )
    session.add(child)
    await session.flush()
    if next_stage == "speakers":
        return await _begin_speakers(session, meeting, child, transcript.id)
    try:
        async with session.begin_nested():
            row = await accept_request(session, parent.meeting_id, parent.requested_by, parent.template_id)
            child.summary_event_id = row.event_id
            await session.flush()
    except Exception:
        logger.error("Cascaded summary request failed for meeting_id=%s", parent.meeting_id)
        await fail_operation(session, child, "request_failed")
    return None


async def settle_summary_operations(session: AsyncSession, event_id: str | None = None) -> None:
    """Copy a settled summary request's outcome to the operation that asked for it."""
    query = (
        select(RegenerationOperation, SummaryRequestOutbox)
        .join(SummaryRequestOutbox, SummaryRequestOutbox.event_id == RegenerationOperation.summary_event_id)
        .where(
            RegenerationOperation.stage == "summary",
            RegenerationOperation.status.in_(REGENERATION_ACTIVE),
            SummaryRequestOutbox.status.in_(("succeeded", "failed")),
        )
    )
    if event_id is not None:
        query = query.where(SummaryRequestOutbox.event_id == event_id)
    for op, request in (await session.execute(query)).all():
        op.status = request.status
        op.started_at = request.started_at
        op.finished_at = request.finished_at or datetime.now(UTC)
        op.failure_cause = request.failure_cause if request.status == "failed" else None
    await session.flush()


async def fail_stale_operations(
    factory: async_sessionmaker[AsyncSession], *, stale_after: timedelta | None = None
) -> int:
    """Fail transcription and speakers runs whose worker never reported back.

    Summary runs are settled from their request by the summary sweeper.
    """
    limit = stale_after if stale_after is not None else timedelta(seconds=stale_after_seconds())
    cutoff = datetime.now(UTC) - limit
    failed = 0
    async with factory() as session, session.begin():
        candidates = (await session.scalars(
            select(RegenerationOperation).where(
                RegenerationOperation.stage.in_(("transcription", "speakers")),
                RegenerationOperation.status.in_(REGENERATION_ACTIVE),
                func.coalesce(RegenerationOperation.started_at, RegenerationOperation.requested_at) < cutoff,
            ).with_for_update(skip_locked=True)
        )).all()
        for op in candidates:
            await fail_operation(session, op, STALE_CAUSE)
            failed += 1
        await settle_summary_operations(session)
    return failed
