"""Durable generation fencing shared by normal processing workers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    RegenerationOperation,
    SessionRecording,
)

ProcessingKind = Literal["transcription", "diarization"]

_RECOVERY_ACTIVE = {"accepted", "dispatch_pending", "processing"}
REGENERATION_ACTIVE = ("accepted", "running")
# The regeneration stage whose operation may drive each kind of worker.
_STAGE_FOR_KIND: dict[str, str] = {"transcription": "transcription", "diarization": "speakers"}


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


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


async def claim_worker_generation(
    session: AsyncSession,
    *,
    meeting_id: str,
    generation: object,
    job_id: object,
    kind: ProcessingKind,
    operation_id: object = None,
) -> bool:
    """Consume a generation once, or consume its matching authorized recovery job.

    A missing control row is legacy, untracked processing and remains available to
    ordinary workers. Recovery and regeneration deliveries always require both a
    persisted operation and its exact durable claim, even when the claim row is missing.
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
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation != claim.generation
        or _is_expired(claim.claim_expires_at)
    ):
        return False

    if operation_id is not None:
        if claim.claim_kind != "recovery" or claim.claim_id != operation_id:
            return False
        claim.claim_kind = kind
        await session.flush()
        return True

    if not isinstance(job_id, str) or not job_id or claim.claim_id is not None or claim.claim_kind is not None:
        return False

    result = await session.execute(
        update(MeetingProcessingClaim)
        .where(
            MeetingProcessingClaim.meeting_id == meeting_id,
            MeetingProcessingClaim.generation == generation,
            MeetingProcessingClaim.claim_id.is_(None),
            MeetingProcessingClaim.claim_kind.is_(None),
            MeetingProcessingClaim.claim_expires_at.is_(None),
        )
        .values(claim_id=job_id, claim_kind=kind)
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
) -> bool:
    """Verify the exact consumed identity again before committing worker effects."""
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
    expected_id = operation_id if operation_id is not None else job_id
    return (
        isinstance(generation, int)
        and not isinstance(generation, bool)
        and generation == claim.generation
        and isinstance(expected_id, str)
        and claim.claim_id == expected_id
        and claim.claim_kind == kind
        and not _is_expired(claim.claim_expires_at)
    )
