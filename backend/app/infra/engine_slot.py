"""Single heavy-engine slot shared by all workers through a PostgreSQL advisory lock.

The lock is a session-level ``pg_advisory_lock`` held on a dedicated connection,
so PostgreSQL releases it on its own when the holder's process or connection dies.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

# RabbitMQ must retain its default consumer_timeout (1800000 ms) or higher.
# Per delivery: 120 s slot wait + 1200 s hard inference limit = 1320 s < 1800 s;
# the remaining 480 s is reserved for SQL, confirmed publication and acknowledgement.
BROKER_CONSUMER_TIMEOUT_S = 1800.0
SLOT_WAIT_TIMEOUT_S = 120.0
ENGINE_CALL_TIMEOUT_S = 1200.0


SLOT_KEY: int = int.from_bytes(
    hashlib.sha256(b"sauri.heavy_engine").digest()[:8], "big", signed=True
)

_TRY_LOCK = text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK = text("SELECT pg_advisory_unlock(:key)")


class EngineSlotTimeout(TimeoutError):  # noqa: N818 - name fixed by design §5
    """The heavy-engine slot was not acquired within the allowed time."""


@asynccontextmanager
async def engine_slot(
    engine: AsyncEngine,
    *,
    kind: str,
    poll_s: float = 2.0,
    timeout_s: float = 3600.0,
) -> AsyncIterator[None]:
    """Hold the heavy-engine slot for the duration of the block.

    Polls ``pg_try_advisory_lock(SLOT_KEY)`` every ``poll_s`` seconds on a
    dedicated autocommit connection and raises :class:`EngineSlotTimeout` after
    ``timeout_s``. The lock is released and the connection closed on every exit.
    """
    conn = await engine.execution_options(isolation_level="AUTOCOMMIT").connect()
    may_hold = False
    try:
        started = time.monotonic()
        deadline = started + timeout_s
        while True:
            may_hold = True  # unknown until the query returns
            acquired = bool((await conn.execute(_TRY_LOCK, {"key": SLOT_KEY})).scalar_one())
            may_hold = acquired
            if acquired:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineSlotTimeout(
                    f"engine slot not acquired within {timeout_s:.1f}s (kind={kind})"
                )
            await asyncio.sleep(min(poll_s, remaining))
        logger.info(
            "engine slot acquired",
            extra={
                "kind": kind,
                "operation": "engine_slot.acquired",
                "wait_seconds": round(time.monotonic() - started, 3),
            },
        )
        yield
    finally:
        await _release(conn, may_hold=may_hold)


async def _release(conn: AsyncConnection, *, may_hold: bool) -> None:
    """Unlock and close; drop the physical connection if the unlock cannot run.

    A connection that may still hold the lock must never return to the pool,
    so any failure (broken connection, cancellation) invalidates it, which
    makes PostgreSQL release the session lock.
    """
    try:
        if may_hold:
            await conn.execute(_UNLOCK, {"key": SLOT_KEY})
    except Exception:
        logger.warning(
            "engine slot unlock failed; discarding connection",
            extra={"operation": "engine_slot.unlock_failed"},
        )
        await _discard(conn)
        return
    except BaseException:
        await _discard(conn)
        raise
    await conn.close()


async def _discard(conn: AsyncConnection) -> None:
    try:
        await conn.invalidate()
    finally:
        await conn.close()
