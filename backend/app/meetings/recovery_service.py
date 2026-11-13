"""Explicit single-meeting recovery: fenced eligibility and transactional outbox.

No broker calls, ingestion replay, pilot arming, or automatic request retries.
Status, preservation verification and outbox delivery are later delivery units.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import NotRequired

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.infra.database import create_engine, create_session_factory
from app.infra.models import (
    Diarization,
    ManualRecoveryPilotGate,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingRecoveryOutbox,
    MeetingSummary,
    ProcessedSummaryEvent,
    SessionRecording,
    SpeakerReview,
    SummaryRequestOutbox,
    Transcript,
)
from app.infra.object_store import ObjectStore, create_object_store
from app.meetings.service import record_transition


class RecoveryResult(TypedDict):
    """Content-free receipt; no operation identity exists for eligibility no-ops."""

    status: str
    reason_code: NotRequired[str]
    operation_id: NotRequired[str]
    meeting_id: NotRequired[str]
    created_at: NotRequired[str]


def _refused(reason: str) -> RecoveryResult:
    return {"status": reason, "reason_code": reason}


def _receipt(operation: MeetingRecoveryOperation, *, duplicate: bool = False) -> RecoveryResult:
    return {
        "status": "already_requested" if duplicate else "accepted",
        "operation_id": operation.id,
        "meeting_id": operation.meeting_id,
        "created_at": operation.created_at.isoformat(),
    }


class MeetingRecoveryService:
    """Own the transaction, including commit errors, without leaking DB details."""

    def __init__(self, object_store_factory: Callable[[], ObjectStore] = create_object_store) -> None:
        self._object_store_factory = object_store_factory

    async def recover(self, meeting_id: str, actor_id: str, idempotency_key: str) -> RecoveryResult:
        if (os.environ.get("SAURI_MANUAL_RECOVERY_MODE", "disabled") != "pilot"
                or os.environ.get("SAURI_RECOVERY_PILOT_MEETING_ID") != meeting_id):
            return _refused("pilot_not_armed")
        engine = create_engine()
        factory = create_session_factory(engine)
        try:
            async with factory() as session, session.begin():
                return await self._recover(session, meeting_id, actor_id, idempotency_key)
        except SQLAlchemyError:
            # Includes NOWAIT contention, read, flush and commit errors. The context
            # manager rolls back all writes; never log SQL parameters or key/media.
            return _refused("eligibility_unverified")
        finally:
            await engine.dispose()

    async def _recover(
        self, session: AsyncSession, meeting_id: str, actor_id: str, key: str,
    ) -> RecoveryResult:
        # Same durable lock as both workers, before any mutable eligibility read.
        # Missing control is legacy/unfenced work: do not create a row or infer idle.
        claim = await session.scalar(select(MeetingProcessingClaim).where(
            MeetingProcessingClaim.meeting_id == meeting_id).with_for_update(nowait=True))
        if claim is None or claim.generation < 1:
            return _refused("eligibility_unverified")
        meeting = await session.scalar(select(Meeting).where(
            Meeting.id == meeting_id).with_for_update(nowait=True))
        if meeting is None or meeting.created_by != actor_id:
            return _refused("not_found")
        key_digest = hashlib.sha256(key.encode()).hexdigest()
        previous = await session.scalar(select(MeetingRecoveryOperation).where(
            MeetingRecoveryOperation.meeting_id == meeting_id,
            MeetingRecoveryOperation.actor_id == actor_id,
            MeetingRecoveryOperation.idempotency_key == key_digest,
        ))
        if previous is not None:
            return _receipt(previous, duplicate=True)

        gate = await session.scalar(select(ManualRecoveryPilotGate).where(
            ManualRecoveryPilotGate.id == 1).with_for_update(nowait=True))
        if (gate is None or gate.allowed_meeting_id != meeting_id
                or gate.authorized_by is None or gate.armed_at is None):
            return _refused("pilot_not_armed")
        if gate.status != "disabled" or gate.pilot_operation_id is not None:
            return _refused("pilot_in_use")
        if meeting.process_state not in {"queued", "transcribing"}:
            return _refused("ineligible_state")
        if any(value is not None for value in (claim.claim_id, claim.claim_kind, claim.claim_expires_at)):
            # Expiration is uncertainty, not proof of worker death.
            return _refused("active_or_pending_work")
        if await session.scalar(select(exists().where(MeetingRecoveryOperation.meeting_id == meeting_id))):
            return _refused("active_or_pending_work")
        # These are all generated-output/work roots in the current schema. Turns,
        # speakers, assignments and review items/receipts require these parents via
        # FKs; no orphan can qualify. Notes (Meeting.title) and retention are read-only.
        for model in (Transcript, Diarization, SpeakerReview, MeetingSummary,
                      SummaryRequestOutbox, ProcessedSummaryEvent):
            if await session.scalar(select(exists().where(model.meeting_id == meeting_id))):
                return _refused("ineligible_artifacts")
        recordings = (await session.scalars(select(SessionRecording).where(
            SessionRecording.meeting_id == meeting_id).with_for_update(nowait=True))).all()
        if len(recordings) != 1:
            return _refused("eligibility_unverified")
        recording = recordings[0]
        now = datetime.now(UTC)
        if (not recording.audio_ref.strip()
                or (recording.expires_at is not None and recording.expires_at <= now)):
            return _refused("eligibility_unverified")
        try:
            # Metadata only. No audio download, presign, engine or queue inspection.
            available = await self._object_store_factory().inspect(recording.audio_ref)
        except Exception:
            return _refused("eligibility_unverified")
        if available != "available":
            return _refused("eligibility_unverified")

        # Every check passed under the shared fence. Advancing the generation makes
        # queued/delayed old-generation AND legacy messages unclaimable by workers.
        # An active/uncertain claim above always rejects; queue totals prove nothing.
        operation_id = str(uuid.uuid4())
        claim.generation += 1
        claim.claim_id = operation_id
        claim.claim_kind = "recovery"
        transition = await record_transition(session, meeting, "guarded_manual_recovery")
        if not transition.successful:
            raise SQLAlchemyError("recovery transition invariant")
        operation = MeetingRecoveryOperation(
            id=operation_id, meeting_id=meeting_id, actor_id=actor_id,
            idempotency_key=key_digest, processing_generation=claim.generation,
            status="accepted", reason_code=None, created_at=now, updated_at=now,
        )
        session.add(operation)
        await session.flush()  # referenced operation must exist before gate/outbox
        session.add(MeetingRecoveryOutbox(
            id=str(uuid.uuid4()), operation_id=operation_id, topic="transcribe",
            # Schema deliberately forbids content/refs. Dispatcher resolves persisted
            # recording from the meeting, never a body-supplied object/owner reference.
            job_identifiers={}, processing_generation=claim.generation,
            delivery_status="pending", attempts=0, created_at=now,
        ))
        gate.status = "running"
        gate.pilot_operation_id = operation_id
        gate.updated_at = now
        await session.flush()
        return _receipt(operation)
