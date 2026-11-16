"""Durable generation fencing shared by normal processing workers."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    RegenerationOperation,
    SessionRecording,
    StateHistory,
)
from app.infra.queue import DeferDelivery

logger = logging.getLogger(__name__)

ProcessingKind = Literal["transcription", "diarization"]

_RECOVERY_ACTIVE = {"accepted", "dispatch_pending", "processing"}
REGENERATION_ACTIVE = ("accepted", "running")
# The regeneration stage whose operation may drive each kind of worker.
_STAGE_FOR_KIND: dict[str, str] = {"transcription": "transcription", "diarization": "speakers"}


# A claim is a lease: its holder renews ``claim_expires_at`` while it works. Once the lease lapses
# the holder is presumed dead and the next delivery of the same generation takes the claim over.
DEFAULT_LEASE_SECONDS = 150.0
DEFAULT_HEARTBEAT_SECONDS = 30.0
# Claims written before leases existed carry no expiry. They count as lapsed this long after the
# meeting's last state change, so a claim left by an older worker cannot block its meeting forever.
DEFAULT_LEGACY_GRACE_SECONDS = 900.0
# Claim holder recorded for a meeting that has no claim row at all (untracked, legacy processing).
UNTRACKED_HOLDER = "untracked"


class ClaimBusy(DeferDelivery):
    """Another worker holds a live lease on this generation; try the delivery again later."""


def seconds_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not 0 < value < 24 * 3600:
        logger.warning("%s='%s' is not a usable number of seconds. Using default %g.", name, raw, default)
        return default
    return value


def lease_seconds() -> float:
    return seconds_from_env("PROCESSING_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)


def heartbeat_seconds() -> float:
    """Pause between renewals; never longer than a third of the lease, so two misses still fit in it."""
    return min(seconds_from_env("PROCESSING_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS), lease_seconds() / 3)


def legacy_grace_seconds() -> float:
    return seconds_from_env("PROCESSING_LEGACY_GRACE_SECONDS", DEFAULT_LEGACY_GRACE_SECONDS)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    return _utc(value) <= datetime.now(UTC)


async def lease_lapsed_at(session: AsyncSession, claim: MeetingProcessingClaim) -> datetime | None:
    """When the lease of a worker-held claim ran out; None while it is still held or reserved.

    A reserved claim (``recovery`` kind, waiting for its worker) and a free one have no lease.
    A claim without an expiry predates leases: it lapses one grace period after the meeting's last
    state change (immediately, for a meeting that never recorded one).
    """
    if claim.claim_id is None or claim.claim_kind in (None, "recovery"):
        return None
    if claim.claim_expires_at is not None:
        lapsed = _utc(claim.claim_expires_at)
    else:
        last_change = await session.scalar(
            select(func.max(StateHistory.occurred_at)).where(StateHistory.meeting_id == claim.meeting_id)
        )
        lapsed = (
            _utc(last_change) + timedelta(seconds=legacy_grace_seconds())
            if last_change is not None else datetime.min.replace(tzinfo=UTC)
        )
    return lapsed if lapsed <= datetime.now(UTC) else None



async def operation_authorizes(
    session: AsyncSession, *, operation_id: str, meeting_id: str, generation: int, kind: ProcessingKind
) -> bool:
    """True when ``operation_id`` is a live recovery or regeneration operation for this job.

    A regeneration operation only drives the worker of its own stage, so a speakers
    operation can never authorize a transcription job and vice versa.
    """
    recovery = await session.get(MeetingRecoveryOperation, operation_id)
    if recovery is not None:
        return (
            recovery.meeting_id == meeting_id
            and recovery.processing_generation == generation
            and recovery.status in _RECOVERY_ACTIVE
        )
    regeneration = await session.get(RegenerationOperation, operation_id)
    return (
        regeneration is not None
        and regeneration.meeting_id == meeting_id
        and regeneration.processing_generation == generation
        and regeneration.stage == _STAGE_FOR_KIND[kind]
        and regeneration.status in REGENERATION_ACTIVE
    )


async def create_processing_generation(
    session: AsyncSession, meeting_id: str
) -> int:
    """Create the initial normal-processing generation in its producer transaction."""
    existing = await session.get(MeetingProcessingClaim, meeting_id)
    if existing is not None:
        raise ValueError("processing generation already exists")
    claim = MeetingProcessingClaim(
        meeting_id=meeting_id,
        generation=1,
        claim_id=None,
        claim_kind=None,
        claim_expires_at=None,
    )
    session.add(claim)
    await session.flush()
    return claim.generation


async def advance_processing_generation(
    session: AsyncSession, meeting_id: str, previous_generation: int
) -> int | None:
    """Advance only from the exact completed generation; never reclaim an old one."""
    claim = await session.scalar(
        select(MeetingProcessingClaim)
        .where(MeetingProcessingClaim.meeting_id == meeting_id)
        .with_for_update()
    )
    if (
        claim is None
        or claim.generation != previous_generation
        or claim.claim_kind != "transcription"
        or claim.claim_id is None
        or _is_expired(claim.claim_expires_at)
    ):
        return None
    claim.generation += 1
    claim.claim_id = None
    claim.claim_kind = None
    claim.claim_expires_at = None
    await session.flush()
    return claim.generation


def _claim_key(claim: MeetingProcessingClaim) -> list[ColumnElement[bool]]:
    """Compare-and-set conditions that pin a claim row to the exact holder just read."""
    return [
        MeetingProcessingClaim.meeting_id == claim.meeting_id,
        MeetingProcessingClaim.generation == claim.generation,
        MeetingProcessingClaim.claim_id.is_(None) if claim.claim_id is None
        else MeetingProcessingClaim.claim_id == claim.claim_id,
        MeetingProcessingClaim.claim_kind.is_(None) if claim.claim_kind is None
        else MeetingProcessingClaim.claim_kind == claim.claim_kind,
    ]


async def claim_worker_generation(
    session: AsyncSession,
    *,
    meeting_id: str,
    generation: object,
    job_id: object,
    kind: ProcessingKind,
    operation_id: object = None,
) -> str | None:
    """Take the claim of a generation for one worker and return the holder id, or None when fenced.

    The first delivery of a generation holds it under its ``job_id`` (a recovery or regeneration
    delivery under its operation id). Every claim is a lease that expires unless renewed. A later
    delivery of the same generation finds the claim in one of three states: the lease is live (another
    worker is working: ``ClaimBusy``, the queue offers the delivery again later), it lapsed (that worker
    died: this delivery takes over under a fresh holder id, so the dead worker's late writes no longer
    verify), or it is not takeable at all (a different kind of job or operation: fenced, None).

    A missing control row is legacy, untracked processing and remains available to ordinary
    workers. Recovery and regeneration deliveries always require both a persisted operation and
    its exact durable claim, even when the claim row is missing.
    """
    if operation_id is not None and (
        not isinstance(operation_id, str)
        or not operation_id
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or not await operation_authorizes(
            session, operation_id=operation_id, meeting_id=meeting_id, generation=generation, kind=kind
        )
    ):
        return None

    claim = await session.scalar(
        select(MeetingProcessingClaim)
        .where(MeetingProcessingClaim.meeting_id == meeting_id)
        .with_for_update()
    )
    if claim is None:
        if operation_id is not None:
            return None
        return job_id if isinstance(job_id, str) and job_id else UNTRACKED_HOLDER
    if not isinstance(generation, int) or isinstance(generation, bool) or generation != claim.generation:
        return None

    if operation_id is not None:
        first = claim.claim_kind == "recovery" and claim.claim_id == operation_id
        holder = operation_id
    else:
        if not isinstance(job_id, str) or not job_id:
            return None
        first = claim.claim_id is None and claim.claim_kind is None
        holder = job_id
    if not first:
        # Taking over needs a worker-held claim of this kind whose lease has run out.
        if claim.claim_id is None or claim.claim_kind != kind:
            return None
        if await lease_lapsed_at(session, claim) is None:
            raise ClaimBusy
        holder = str(uuid.uuid4())

    result = await session.execute(
        update(MeetingProcessingClaim)
        .where(*_claim_key(claim))
        .values(
            claim_id=holder, claim_kind=kind,
            claim_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds()),
        )
        .returning(MeetingProcessingClaim.meeting_id)
    )
    if result.scalar_one_or_none() != meeting_id:
        return None
    if not first:
        logger.warning("Processing claim taken over after its lease lapsed; kind=%s meeting_id=%s", kind, meeting_id)
    return holder


async def renew_claim(
    factory: async_sessionmaker[AsyncSession],
    *,
    meeting_id: str,
    generation: int,
    holder: str,
    kind: ProcessingKind,
    lease_s: float,
) -> bool:
    """Extend the lease of the holder's own, still-live claim; False when it was lost or already lapsed."""
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        result = await session.execute(
            update(MeetingProcessingClaim)
            .where(
                MeetingProcessingClaim.meeting_id == meeting_id,
                MeetingProcessingClaim.generation == generation,
                MeetingProcessingClaim.claim_id == holder,
                MeetingProcessingClaim.claim_kind == kind,
                MeetingProcessingClaim.claim_expires_at > now,
            )
            .values(claim_expires_at=now + timedelta(seconds=lease_s))
            .returning(MeetingProcessingClaim.meeting_id)
        )
        return result.scalar_one_or_none() == meeting_id


async def release_worker_claim(
    session: AsyncSession,
    *,
    meeting_id: str,
    generation: object,
    holder: str,
    kind: ProcessingKind,
    operation_id: object = None,
) -> bool:
    """Give the claim back so the next delivery of this generation can take it at once.

    Only the current holder can release; a claim already taken over is left alone. A run driven by
    an operation returns to the reserved state its dispatcher left, a normal run to unclaimed.
    """
    reserved = operation_id if isinstance(operation_id, str) else None
    result = await session.execute(
        update(MeetingProcessingClaim)
        .where(
            MeetingProcessingClaim.meeting_id == meeting_id,
            MeetingProcessingClaim.generation == generation,
            MeetingProcessingClaim.claim_id == holder,
            MeetingProcessingClaim.claim_kind == kind,
        )
        .values(
            claim_id=reserved, claim_kind="recovery" if reserved is not None else None, claim_expires_at=None
        )
        .returning(MeetingProcessingClaim.meeting_id)
    )
    return result.scalar_one_or_none() == meeting_id


async def verify_worker_binding(
    session: AsyncSession, *, meeting_id: str, owner_id: str, recording_id: str
) -> bool:
    """Re-read persisted identity in the transaction that performs worker writes."""
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None or meeting.created_by != owner_id:
        return False
    recording = await session.scalar(
        select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
    )
    return recording is not None and recording.id == recording_id


async def verify_worker_generation(
    session: AsyncSession,
    *,
    meeting_id: str,
    generation: object,
    job_id: object,
    kind: ProcessingKind,
    operation_id: object = None,
    holder: str | None = None,
) -> bool:
    """Verify the exact consumed identity again before committing worker effects.

    ``holder`` is the id ``claim_worker_generation`` returned; it differs from the message identity
    once a claim has been taken over, and it is what fences the previous holder out.
    """
    if operation_id is not None and (
        not isinstance(operation_id, str)
        or not operation_id
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or not await operation_authorizes(
            session, operation_id=operation_id, meeting_id=meeting_id, generation=generation, kind=kind
        )
    ):
        return False

    claim = await session.scalar(
        select(MeetingProcessingClaim)
        .where(MeetingProcessingClaim.meeting_id == meeting_id)
        .with_for_update()
    )
    if claim is None:
        return operation_id is None
    expected_id = holder if holder is not None else operation_id if operation_id is not None else job_id
    return (
        isinstance(generation, int)
        and not isinstance(generation, bool)
        and generation == claim.generation
        and isinstance(expected_id, str)
        and claim.claim_id == expected_id
        and claim.claim_kind == kind
        and not _is_expired(claim.claim_expires_at)
    )
