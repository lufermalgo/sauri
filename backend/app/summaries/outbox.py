"""Durable at-least-once delivery of committed summary requests (D15)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import SummaryRequestOutbox
from app.infra.queue import JobQueue

logger = logging.getLogger(__name__)


async def dispatch_pending(factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> int:
    """Lock one row at a time; only confirmed publications become delivered.

    A crash after broker confirmation but before DB commit republishes the same
    event_id. Consumer idempotency (T12) is required for this at-least-once seam.
    """
    delivered = 0
    while True:
        async with factory() as session, session.begin():
            query = (select(SummaryRequestOutbox)
                     .where(SummaryRequestOutbox.delivered_at.is_(None))
                     .order_by(SummaryRequestOutbox.event_id).limit(1))
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = await session.scalar(query)
            if row is None:
                return delivered
            await queue.publish("summarize", {
                "event_id": row.event_id, "meeting_id": row.meeting_id,
                "transcript_id": row.transcript_id, "generation": row.generation,
                "template_id": row.template_id, "template_version": row.template_version,
                "instructions_snapshot": row.instructions_snapshot,
            })
            row.delivered_at = datetime.now(UTC)
        delivered += 1


@asynccontextmanager
async def recover_outbox(
    factory: async_sessionmaker[AsyncSession], queue: JobQueue, interval: float = 2.0,
) -> AsyncIterator[None]:
    """Run at startup and periodically; reconnect after broker outages."""
    async def recover() -> None:
        while True:
            try:
                await queue.connect()
                await dispatch_pending(factory, queue)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Summary outbox delivery failed; will retry")
            finally:
                await queue.disconnect()
            await asyncio.sleep(interval)

    worker = asyncio.create_task(recover(), name="summary-outbox-recovery")
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
