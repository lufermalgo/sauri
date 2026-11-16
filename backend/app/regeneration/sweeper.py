"""Release meetings whose explicit regeneration run was lost (worker crash, lost message)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.regeneration.service import fail_stale_operations

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 60


async def run_stale_operation_sweeper(
    factory: async_sessionmaker[AsyncSession], interval_seconds: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Background loop of the worker."""
    while True:
        try:
            failed = await fail_stale_operations(factory)
            if failed:
                logger.warning("Marked %d stale regeneration operation(s) as failed", failed)
        except Exception:
            logger.exception("Error in regeneration stale-operation sweep")
        await asyncio.sleep(interval_seconds)
