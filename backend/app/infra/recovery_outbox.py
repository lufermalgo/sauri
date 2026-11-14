"""Initial delivery of committed, explicitly accepted recovery intent.

Never initiates recovery, replays ingestion or changes meeting/claim state. This
startup pass is not a scheduler or the ambiguous-ack retry protocol (T19/T20).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingRecoveryOutbox,
    SessionRecording,
)
from app.infra.queue import JobQueue

logger = logging.getLogger(__name__)


async def dispatch_pending_recoveries(
    queue: JobQueue, session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Deliver the committed pending set once; mark only confirmed publishes.

    Lock outbox rows across publication so simultaneous startup passes do not
    publish the same pending row. Consumers do not lock outbox rows. A crash or
    ambiguous broker acknowledgement can still leave a pending row after actual
    delivery: durable retry/dedup evidence belongs to T19/T20, not this slice.
    """
    published = 0
    async with session_factory() as session, session.begin():
        rows = (await session.execute(
            select(MeetingRecoveryOutbox, MeetingRecoveryOperation)
            .join(MeetingRecoveryOperation, MeetingRecoveryOperation.id == MeetingRecoveryOutbox.operation_id)
            .where(
                MeetingRecoveryOutbox.delivery_status == "pending",
                MeetingRecoveryOutbox.topic == "transcribe",
                MeetingRecoveryOperation.status.in_(("accepted", "dispatch_pending")),
                MeetingRecoveryOutbox.processing_generation == MeetingRecoveryOperation.processing_generation,
            )
            .order_by(MeetingRecoveryOutbox.created_at, MeetingRecoveryOutbox.id)
            .with_for_update(of=MeetingRecoveryOutbox, skip_locked=True)
        )).all()
        for outbox, operation in rows:
            meeting = await session.get(Meeting, operation.meeting_id)
            claim = await session.get(MeetingProcessingClaim, operation.meeting_id)
            recordings = (await session.scalars(select(SessionRecording).where(
                SessionRecording.meeting_id == operation.meeting_id,
            ))).all()
            if (meeting is None or meeting.created_by != operation.actor_id
                    or claim is None or claim.generation != operation.processing_generation
                    or claim.claim_kind != "recovery" or claim.claim_id != operation.id
                    or claim.claim_expires_at is not None or len(recordings) != 1):
                logger.warning("Recovery delivery skipped; reason=binding_unverified operation_id=%s", operation.id)
                continue
            # Only opaque persisted identifiers. Worker resolves the canonical media
            # reference itself; neither outbox nor broker payload carries content.
            payload = {
                "operation_id": operation.id, "job_id": operation.id,
                "generation": operation.processing_generation,
                "meeting_id": operation.meeting_id, "owner_id": meeting.created_by,
                "recording_id": recordings[0].id,
            }
            outbox.attempts += 1
            try:
                await queue.publish("transcribe", payload)
            except Exception:
                # Never log exception text: brokers may echo raw payloads/URLs.
                operation.status = "dispatch_pending"
                operation.reason_code = "publish_failed"
                operation.updated_at = datetime.now(UTC)
                logger.warning("Recovery delivery pending; reason=publish_failed operation_id=%s", operation.id)
                continue
            outbox.delivery_status = "published"
            published += 1
            logger.info("Recovery delivery published; operation_id=%s", operation.id)
    return published
