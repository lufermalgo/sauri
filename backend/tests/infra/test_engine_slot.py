"""engine_slot against a real PostgreSQL (Propiedad 10, Requisito 3.3).

Advisory-lock semantics cannot be mocked meaningfully, so these tests need a
disposable PostgreSQL in SAURI_QA_POSTGRES_URL and are skipped without it.
They take only advisory locks and create no tables.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.infra.engine_slot import SLOT_KEY, EngineSlotTimeout, engine_slot

POLL_S = 0.05
_CLASSID = (SLOT_KEY >> 32) & 0xFFFFFFFF
_OBJID = SLOT_KEY & 0xFFFFFFFF
_HOLDERS_SQL = text(
    "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted"
    " AND classid::bigint = :classid AND objid::bigint = :objid AND objsubid = 1"
)

EngineFactory = Callable[[str], AsyncEngine]


@pytest.fixture
def pg_url() -> str:
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    return url


@pytest.fixture
async def make_engine(pg_url: str) -> AsyncIterator[EngineFactory]:
    """Engines without pooling, tagged by application_name, so closed means gone."""
    engines: list[AsyncEngine] = []

    def factory(app_name: str) -> AsyncEngine:
        engine = create_async_engine(
            pg_url,
            poolclass=NullPool,
            connect_args={"server_settings": {"application_name": app_name}},
        )
        engines.append(engine)
        return engine

    yield factory
    for engine in engines:
        await engine.dispose()


@pytest.fixture
async def observer(make_engine: EngineFactory) -> AsyncEngine:
    engine = make_engine("engine_slot_observer")
    assert await _holder_pids(engine) == [], "slot already held before the test"
    return engine


async def _holder_pids(observer: AsyncEngine) -> list[int]:
    async with observer.connect() as conn:
        rows = await conn.execute(_HOLDERS_SQL, {"classid": _CLASSID, "objid": _OBJID})
        return [row[0] for row in rows]


async def _backends(observer: AsyncEngine, app_name: str) -> int:
    async with observer.connect() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM pg_stat_activity WHERE application_name = :n"),
            {"n": app_name},
        )
        return int(result.scalar_one())


async def _wait_until_held(observer: AsyncEngine) -> None:
    for _ in range(200):
        if await _holder_pids(observer):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("slot never acquired")


def test_slot_key_is_stable() -> None:
    assert SLOT_KEY == -8342842067975809180


async def test_concurrent_users_never_overlap(
    make_engine: EngineFactory, observer: AsyncEngine
) -> None:
    engines = [make_engine(f"engine_slot_user_{i}") for i in range(2)]
    intervals: list[tuple[float, float]] = []

    async def use(engine: AsyncEngine, kind: str) -> None:
        async with engine_slot(engine, kind=kind, poll_s=0.01, timeout_s=10):
            entered = time.monotonic()
            await asyncio.sleep(0.03)
            intervals.append((entered, time.monotonic()))

    for _ in range(5):
        await asyncio.gather(
            use(engines[0], "transcription"),
            use(engines[1], "diarization"),
            use(engines[0], "summary"),
            use(engines[1], "transcription"),
        )

    assert len(intervals) == 20
    ordered = sorted(intervals)
    for (_, previous_exit), (next_enter, _) in zip(ordered, ordered[1:], strict=False):
        assert previous_exit <= next_enter
    assert await _holder_pids(observer) == []


async def test_waiter_acquires_when_holder_connection_dies(
    make_engine: EngineFactory, observer: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    holder_engine = make_engine("engine_slot_holder")
    waiter_engine = make_engine("engine_slot_waiter")
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with engine_slot(holder_engine, kind="transcription", poll_s=POLL_S):
            await release_holder.wait()

    async def waiter() -> float:
        async with engine_slot(waiter_engine, kind="diarization", poll_s=POLL_S, timeout_s=10):
            return time.monotonic()

    holder_task = asyncio.create_task(holder())
    await _wait_until_held(observer)
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(3 * POLL_S)
    assert not waiter_task.done()

    [holder_pid] = await _holder_pids(observer)
    async with observer.connect() as conn:
        await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": holder_pid})
    killed_at = time.monotonic()

    acquired_at = await asyncio.wait_for(waiter_task, timeout=5)
    assert acquired_at - killed_at <= POLL_S + 0.5

    # The holder's unlock hits a dead connection: it must exit cleanly.
    with caplog.at_level(logging.WARNING, logger="app.infra.engine_slot"):
        release_holder.set()
        await asyncio.wait_for(holder_task, timeout=5)
    assert any(r.operation == "engine_slot.unlock_failed" for r in caplog.records)
    assert await _holder_pids(observer) == []
    assert await _backends(observer, "engine_slot_holder") == 0
    assert await _backends(observer, "engine_slot_waiter") == 0


async def test_timeout_raises_and_leaves_no_lock(
    make_engine: EngineFactory, observer: AsyncEngine
) -> None:
    holder_engine = make_engine("engine_slot_holder")
    waiter_engine = make_engine("engine_slot_waiter")
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with engine_slot(holder_engine, kind="summary", poll_s=POLL_S):
            await release_holder.wait()

    holder_task = asyncio.create_task(holder())
    await _wait_until_held(observer)
    [holder_pid] = await _holder_pids(observer)

    started = time.monotonic()
    with pytest.raises(EngineSlotTimeout):
        async with engine_slot(waiter_engine, kind="diarization", poll_s=POLL_S, timeout_s=0.3):
            pytest.fail("slot must not be acquired while held")
    assert 0.3 <= time.monotonic() - started < 2
    assert await _holder_pids(observer) == [holder_pid]
    assert await _backends(observer, "engine_slot_waiter") == 0

    release_holder.set()
    await holder_task
    assert await _holder_pids(observer) == []
    assert await _backends(observer, "engine_slot_holder") == 0


async def test_cancellation_while_waiting_leaks_nothing(
    make_engine: EngineFactory, observer: AsyncEngine
) -> None:
    holder_engine = make_engine("engine_slot_holder")
    waiter_engine = make_engine("engine_slot_waiter")
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with engine_slot(holder_engine, kind="transcription", poll_s=POLL_S):
            await release_holder.wait()

    async def waiter() -> None:
        async with engine_slot(waiter_engine, kind="summary", poll_s=POLL_S, timeout_s=10):
            pytest.fail("slot must not be acquired while held")

    holder_task = asyncio.create_task(holder())
    await _wait_until_held(observer)
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(3 * POLL_S)
    assert await _backends(observer, "engine_slot_waiter") == 1

    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    assert await _backends(observer, "engine_slot_waiter") == 0

    release_holder.set()
    await holder_task
    assert await _holder_pids(observer) == []
    assert await _backends(observer, "engine_slot_holder") == 0


async def test_acquisition_log_is_structured(
    make_engine: EngineFactory, observer: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    engine = make_engine(f"engine_slot_{uuid.uuid4().hex[:8]}")
    with caplog.at_level(logging.INFO, logger="app.infra.engine_slot"):
        async with engine_slot(engine, kind="transcription", poll_s=POLL_S):
            pass
    [record] = [r for r in caplog.records if getattr(r, "operation", None) == "engine_slot.acquired"]
    assert record.kind == "transcription"
    assert isinstance(record.wait_seconds, float)
    assert await _holder_pids(observer) == []
