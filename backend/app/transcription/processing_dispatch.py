"""Durable exact-revision outbox delivery to the existing at-least-once queue."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import ProcessingRevision, ProcessingRevisionOutbox, ProcessingStage, RecordingProcessingState
from app.infra.queue import JobQueue

logger = logging.getLogger(__name__)


async def dispatch_pending(
    session_factory: async_sessionmaker[AsyncSession], queue: JobQueue, *, limit: int = 32
) -> int:
    """Publish only committed events; a failed/uncertain publish stays retryable.

    Locking includes the broker publish so concurrent dispatchers cannot claim
    the same event at once. A crash after publish but before commit redelivers
    the same ID; the stage lease and finalized revision make replay harmless.
    """
    delivered = 0
    for _ in range(limit):
        async with session_factory() as session, session.begin():
            event = await session.scalar(
                select(ProcessingRevisionOutbox)
                .where(ProcessingRevisionOutbox.delivery_status == "pending")
                .order_by(ProcessingRevisionOutbox.created_at, ProcessingRevisionOutbox.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if event is None:
                break
            try:
                await queue.publish(
                    "processing_revision",
                    {
                        "event_id": event.id,
                        "event_type": event.event_type,
                        "processing_revision_id": event.processing_revision_id,
                        "recording_id": event.recording_id,
                    },
                )
            except Exception:
                logger.exception("Revision outbox publication failed; event remains pending")
                break
            event.delivery_status = "delivered"
            delivered += 1
    return delivered


async def recover_unfinished(
    session_factory: async_sessionmaker[AsyncSession], queue: JobQueue, *, limit: int = 32
) -> int:
    """Replay the original event ID for an expired claim or stranded finalizer.

    No new outbox entry is allocated, and a published-but-unacknowledged message
    may be repeated; claim fencing and exact-candidate finalization absorb it.
    """
    count = 0
    async with session_factory() as session:
        # Stream the entire in-flight set in bounded batches; selecting just
        # the first `limit` rows would starve later recordings indefinitely.
        states = await session.stream_scalars(
            select(RecordingProcessingState)
            .where(RecordingProcessingState.in_flight_revision_id.is_not(None))
            .order_by(RecordingProcessingState.recording_id)
            .execution_options(yield_per=limit)
        )
        async for state in states:
            revision = await session.get(ProcessingRevision, state.in_flight_revision_id)
            if revision is None:
                continue
            stages = (
                await session.scalars(
                    select(ProcessingStage).where(ProcessingStage.processing_revision_id == revision.id)
                )
            ).all()
            by_stage = {stage.stage: stage for stage in stages}
            transcription = by_stage.get("transcription")
            diarization = by_stage.get("diarization")
            target = "processing_revision_admitted"
            if transcription is not None and transcription.status == "completed":
                target = "transcription_completed"
                if diarization is not None and diarization.status == "completed":
                    target = "diarization_completed"
            elif transcription is not None and transcription.status == "running":
                expiry = transcription.lease_expires_at
                if expiry is not None:
                    deadline = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
                    if deadline > datetime.now(UTC):
                        continue
            if target == "transcription_completed" and diarization is not None and diarization.status == "running":
                expiry = diarization.lease_expires_at
                if expiry is not None:
                    deadline = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
                    if deadline > datetime.now(UTC):
                        continue
            event = await session.scalar(
                select(ProcessingRevisionOutbox).where(
                    ProcessingRevisionOutbox.processing_revision_id == revision.id,
                    ProcessingRevisionOutbox.event_type == target,
                    ProcessingRevisionOutbox.delivery_status == "delivered",
                )
            )
            if event is None:
                continue  # pending events are handled by dispatch_pending
            await queue.publish(
                "processing_revision",
                {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "processing_revision_id": revision.id,
                    "recording_id": revision.recording_id,
                },
            )
            count += 1
    return count


async def dispatch_forever(
    session_factory: async_sessionmaker[AsyncSession], queue: JobQueue, *, interval: float = 2.0
) -> None:
    """Poll after startup too, recovering committed events after broker outages."""
    last_recovery = 0.0
    while True:
        try:
            await dispatch_pending(session_factory, queue)
            now = asyncio.get_running_loop().time()
            if now - last_recovery >= 30.0:
                await recover_unfinished(session_factory, queue)
                last_recovery = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Revision outbox dispatch will retry")
        await asyncio.sleep(interval)
