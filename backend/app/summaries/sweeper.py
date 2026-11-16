"""Fail summary requests whose broker message was lost, so nobody waits forever."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import ProcessedSummaryEvent, SummaryRequestOutbox

logger = logging.getLogger(__name__)

# Two attempts of up to ~29 minutes each (broker consumer timeout) plus the retry delay
# stay below ~61 minutes; the rest is margin.
DEFAULT_STALE_AFTER_SECONDS = 4500
SWEEP_INTERVAL_SECONDS = 60
STALE_CAUSE = "stale_request"


def stale_after_seconds() -> int:
    raw = os.environ.get("SUMMARY_STALE_AFTER_SECONDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_STALE_AFTER_SECONDS
    except ValueError:
        logger.warning("SUMMARY_STALE_AFTER_SECONDS is not an integer; using the default.")
        return DEFAULT_STALE_AFTER_SECONDS
    return value if value > 0 else DEFAULT_STALE_AFTER_SECONDS


async def fail_stale_requests(
    factory: async_sessionmaker[AsyncSession], *, stale_after: timedelta | None = None,
) -> int:
    """Mark delivered requests that never settled as failed; return how many changed.

    A single conditional UPDATE: only ``pending``/``running`` rows are candidates, so a
    settled request is never touched and a second pass finds nothing. Rows with a
    stored summary are excluded as a defense (success commits status and summary together).
    ``pending`` rows count only once delivered; undelivered ones are still the outbox's job.
    """
    limit = stale_after if stale_after is not None else timedelta(seconds=stale_after_seconds())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        result = await session.execute(
            update(SummaryRequestOutbox)
            .where(
                SummaryRequestOutbox.status.in_(("pending", "running")),
                SummaryRequestOutbox.delivered_at.is_not(None),
                func.coalesce(SummaryRequestOutbox.started_at, SummaryRequestOutbox.delivered_at) < now - limit,
                ~exists().where(ProcessedSummaryEvent.event_id == SummaryRequestOutbox.event_id),
            )
            .values(status="failed", failure_cause=STALE_CAUSE, finished_at=now)
            .execution_options(synchronize_session=False)
        )
    return int(getattr(result, "rowcount", 0) or 0)


async def run_stale_request_sweeper(
    factory: async_sessionmaker[AsyncSession], interval_seconds: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Background loop of the worker."""
    logger.info("Summary stale-request sweeper started (stale after %ds)", stale_after_seconds())
    while True:
        try:
            failed = await fail_stale_requests(factory)
            if failed:
                logger.warning("Marked %d stale summary request(s) as failed", failed)
        except Exception:
            logger.exception("Error in summary stale-request sweep")
        await asyncio.sleep(interval_seconds)
