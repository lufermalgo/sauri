"""Real PostgreSQL queue properties and lifecycle checks (#1201).

Every test owns a migrated, disposable database. No default service is contacted.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url

from alembic import command
from app.infra.models import JobMessage
from app.infra.queue import DeferDelivery, create_job_queue
from app.infra.queue_postgres import PostgresJobQueue
from app.infra.queue_rabbitmq import RabbitMQJobQueue
from app.worker import stop_gracefully

BACKEND = Path(__file__).resolve().parents[2]
PROPERTY = settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def migration_config() -> Config:
    # No logging config: Alembic must not disable pytest's/application loggers.
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


@pytest.fixture
async def pg_url(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    assert url.host in {"127.0.0.1", "localhost", "::1"}, "loopback QA server required"
    database = f"sauri_qa_queue_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    target = url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        monkeypatch.delenv("DATABASE_PASSWORD_FILE", raising=False)
        monkeypatch.setenv("DATABASE_URL", target)
        monkeypatch.setenv("APP_ENV", "test")
        await asyncio.to_thread(command.upgrade, migration_config(), "head")
        yield target
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()


async def eventually(check: Callable[[], Awaitable[bool]], timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(0.01)


async def rows(queue: PostgresJobQueue) -> list[JobMessage]:
    async with queue._factory() as session:
        return list((await session.scalars(select(JobMessage))).all())


@PROPERTY
@given(
    consumers=st.integers(1, 5), failures=st.lists(st.booleans(), min_size=1, max_size=12), retries=st.integers(0, 3),
)
async def test_property_1_concurrent_delivery_settles_once(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, consumers: int, failures: list[bool], retries: int,
) -> None:
    monkeypatch.setenv("ASR_MAX_RETRIES", str(retries))
    queues = [PostgresJobQueue(pg_url) for _ in range(consumers)]
    active: set[int] = set()
    overlap: list[int] = []
    calls: Counter[int] = Counter()
    try:
        for queue in queues:
            await queue.connect()
        async with queues[0]._engine.begin() as conn:
            await conn.execute(text("TRUNCATE job_messages"))

        async def handler(message: dict[str, Any]) -> None:
            index = message["index"]
            if index in active:
                overlap.append(index)
            active.add(index)
            calls[index] += 1
            try:
                await asyncio.sleep(0.002)
                if failures[index]:
                    raise ValueError("synthetic failure")
            finally:
                active.discard(index)

        for queue in queues:
            await queue.subscribe("transcribe", handler)
        for index in range(len(failures)):
            await queues[0].publish("transcribe", {"index": index})

        async def settled() -> bool:
            remaining = await rows(queues[0])
            return len(calls) == len(failures) and all(m.topic == "transcribe.failed" for m in remaining)

        await eventually(settled)
        assert not overlap
        assert calls == Counter({i: retries + 1 if fail else 1 for i, fail in enumerate(failures)})
        remaining = await rows(queues[0])
        assert Counter(m.body["index"] for m in remaining) == Counter(i for i, fail in enumerate(failures) if fail)
        assert all(m.attempts == 0 and m.locked_until is None for m in remaining)
    finally:
        for queue in queues:
            await queue.disconnect()


@PROPERTY
@given(attempts=st.integers(0, 10), deferrals=st.integers(1, 5))
async def test_property_1_defer_parks_without_incrementing_attempts(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, attempts: int, deferrals: int,
) -> None:
    monkeypatch.setenv("QUEUE_DEFER_SECONDS", "30")
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    try:
        await queue.publish("transcribe", {"deferred": True})
        async with queue._factory() as session, session.begin():
            await session.execute(update(JobMessage).values(attempts=attempts, headers={"x-sauri-retries": attempts}))

        async def defer(_: dict[str, Any]) -> None:
            raise DeferDelivery

        for _ in range(deferrals):
            delivery = await queue._claim("transcribe")
            assert delivery is not None
            await queue._deliver(delivery, defer, 3, 0, 30)
            parked, = await rows(queue)
            assert parked.attempts == attempts
            assert parked.headers == {"x-sauri-retries": attempts}
            assert parked.locked_until is None
            assert parked.available_at > parked.created_at
            assert await queue.pending_count("transcribe") == 0
            assert await queue._claim("transcribe") is None
            async with queue._factory() as session, session.begin():
                await session.execute(update(JobMessage).values(available_at=func.now()))
        delivery = await queue._claim("transcribe")
        assert delivery is not None
        await queue._settle(delivery, "ack")
        assert await rows(queue) == []
    finally:
        await queue.disconnect()


@PROPERTY
@given(consumers=st.integers(1, 5), seconds=st.integers(1, 1800))
async def test_property_2_crash_redelivers_only_after_lease_expiry(
    pg_url: str, consumers: int, seconds: int,
) -> None:
    crashed = PostgresJobQueue(pg_url)
    survivor = PostgresJobQueue(pg_url)
    await crashed.connect()
    await survivor.connect()
    try:
        await crashed.publish("transcribe", {"crash": True})
        original = await crashed._claim("transcribe")
        assert original is not None
        assert original.locked_until - original.available_at >= timedelta(seconds=1799)
        # No consumer task owns this claim: closing its connections models a process disappearing.
        await crashed.disconnect()
        async with survivor._factory() as session, session.begin():
            await session.execute(update(JobMessage).values(locked_until=func.now() + timedelta(seconds=seconds)))
        assert await survivor.pending_count("transcribe") == 0
        assert await asyncio.gather(*(survivor._claim("transcribe") for _ in range(consumers))) == [None] * consumers
        async with survivor._factory() as session, session.begin():
            await session.execute(update(JobMessage).values(locked_until=func.now() - timedelta(seconds=1)))
        assert await survivor.pending_count("transcribe") == 1
        claims = await asyncio.gather(*(survivor._claim("transcribe") for _ in range(consumers)))
        reclaimed, = [m for m in claims if m is not None]
        assert reclaimed.id == original.id
        assert reclaimed.attempts == 0
        # A late acknowledgement or terminal event from the dead owner is fenced out.
        await survivor._settle(original, "failed")
        assert len(await rows(survivor)) == 1
        await survivor._settle(reclaimed, "ack")
        assert await rows(survivor) == []
    finally:
        await crashed.disconnect()
        await survivor.disconnect()


async def test_retry_defaults_delays_headers_and_terminal_retention(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SUMMARIZE_MAX_RETRIES", "SUMMARIZE_RETRY_DELAY_SECONDS", "ASR_MAX_RETRIES"):
        monkeypatch.delenv(name, raising=False)
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    try:
        async def fail(_: dict[str, Any]) -> None:
            raise ValueError("synthetic failure")

        await queue.subscribe("summarize", fail)
        await queue.publish("summarize", {"event_id": "synthetic"})

        async def parked() -> bool:
            messages = await rows(queue)
            return len(messages) == 1 and messages[0].attempts == 1 and messages[0].locked_until is None

        await eventually(parked)
        message, = await rows(queue)
        assert message.headers == {"x-sauri-retries": 1}
        assert message.available_at - message.created_at >= timedelta(seconds=30)
        assert await queue.pending_count("summarize") == 0
        async with queue._factory() as session, session.begin():
            await session.execute(update(JobMessage).values(available_at=func.now()))
            await queue._notify(session)

        async def terminal() -> bool:
            return [m.topic for m in await rows(queue)] == ["summarize.failed"]

        await eventually(terminal)
        await queue.stop_consuming()
        assert await queue.wait_idle(2)
        # Exhausted terminal handlers must retain the same durable event, never .failed.failed.
        for _ in range(6):
            delivery = await queue._claim("summarize.failed")
            assert delivery is not None
            await queue._deliver(delivery, fail, 3, 0, 30)
        remaining, = await rows(queue)
        assert remaining.topic == "summarize.failed"
        assert remaining.attempts == 3
        assert await queue.pending_count("summarize.failed") == 1
    finally:
        await queue.disconnect()


async def test_stop_drains_and_cancellation_releases_without_retry(pg_url: str) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    started, finish = asyncio.Event(), asyncio.Event()

    async def handler(_: dict[str, Any]) -> None:
        started.set()
        await finish.wait()

    try:
        await queue.subscribe("transcribe", handler)
        await queue.publish("transcribe", {"first": True})
        await asyncio.wait_for(started.wait(), 3)
        await queue.publish("transcribe", {"second": True})
        await queue.stop_consuming()
        assert not await queue.wait_idle(0.01)
        finish.set()
        assert await queue.wait_idle(3)
        assert await queue.pending_count("transcribe") == 1
        await queue.disconnect()
        await queue.connect()
        started.clear()
        finish.clear()
        await queue.subscribe("transcribe", handler)
        await asyncio.wait_for(started.wait(), 3)
        assert not await stop_gracefully(queue, 0.01)
        message, = await rows(queue)
        assert message.locked_until is None and message.attempts == 0
        assert await queue.pending_count("transcribe") == 1
    finally:
        await queue.disconnect()


async def test_notifications_wake_other_instances_and_polling_survives_listener_loss(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer, consumer = PostgresJobQueue(pg_url), PostgresJobQueue(pg_url)
    await producer.connect()
    await consumer.connect()
    received = asyncio.Event()

    async def handler(_: dict[str, Any]) -> None:
        received.set()

    try:
        # A long fallback makes prompt delivery evidence of a real cross-connection NOTIFY.
        monkeypatch.setattr("app.infra.queue_postgres.POLL_SECONDS", 60)
        await consumer.subscribe("notify", handler)
        await asyncio.sleep(0.1)
        await producer.publish("notify", {"notify": True})
        await asyncio.wait_for(received.wait(), 2)
        await consumer.stop_consuming()
        assert await consumer.wait_idle(2)
        await consumer.disconnect()
        monkeypatch.setattr("app.infra.queue_postgres.POLL_SECONDS", 0.05)
        await consumer.connect()
        await consumer._listener.close()

        async def no_listener() -> None:
            pass

        monkeypatch.setattr(consumer, "_ensure_listener", no_listener)
        received.clear()
        await consumer.subscribe("poll", handler)
        await asyncio.sleep(0.1)
        await producer.publish("poll", {"poll": True})
        await asyncio.wait_for(received.wait(), 2)
    finally:
        await producer.disconnect()
        await consumer.disconnect()


async def test_migration_roundtrip_and_schema(pg_url: str) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    try:
        async with queue._engine.connect() as conn:
            columns = (await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'job_messages'"
            ))).scalars().all()
            assert set(columns) == {
                "id", "topic", "body", "headers", "attempts", "available_at", "locked_until", "created_at",
            }
            index = await conn.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'job_messages_ready'"))
            assert "(topic, available_at) WHERE (locked_until IS NULL)" in index
        config = migration_config()
        await asyncio.to_thread(command.downgrade, config, "029_meeting_recorded_at")
        async with queue._engine.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('job_messages')")) is None
        await asyncio.to_thread(command.upgrade, config, "head")
        await queue.publish("join", {"synthetic": True})
        message, = await rows(queue)
        assert message.attempts == 0 and message.headers == {} and message.locked_until is None
    finally:
        await queue.disconnect()


def test_factory_defaults_to_rabbitmq_and_selects_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUEUE_KIND", raising=False)
    monkeypatch.delenv("QUEUE_BROKER_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("QUEUE_BROKER_URL", "amqp://synthetic:synthetic@127.0.0.1/")
    assert isinstance(create_job_queue(), RabbitMQJobQueue)
    monkeypatch.setenv("QUEUE_KIND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://synthetic:synthetic@127.0.0.1/sauri_qa_unused")
    monkeypatch.delenv("DATABASE_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("QUEUE_BROKER_URL")
    assert isinstance(create_job_queue(), PostgresJobQueue)
    monkeypatch.setenv("QUEUE_KIND", "unknown")
    with pytest.raises(ValueError, match="Unsupported QUEUE_KIND"):
        create_job_queue()


async def test_failed_publication_and_original_delete_roll_back_together(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    try:
        await queue.publish("transcribe", {"synthetic": True})
        delivery = await queue._claim("transcribe")
        assert delivery is not None
        notify = queue._notify

        async def fail_transaction(session: Any) -> None:
            await session.flush()  # execute both INSERT .failed and DELETE original
            raise RuntimeError("synthetic transaction failure")

        monkeypatch.setattr(queue, "_notify", fail_transaction)
        with pytest.raises(RuntimeError, match="synthetic transaction"):
            await queue._settle(delivery, "failed")
        original, = await rows(queue)
        assert original.id == delivery.id and original.topic == "transcribe"
        monkeypatch.setattr(queue, "_notify", notify)
        await asyncio.gather(*(queue._settle(delivery, "failed") for _ in range(3)))
        terminal, = await rows(queue)
        assert terminal.topic == "transcribe.failed" and terminal.body == delivery.body
    finally:
        await queue.disconnect()


async def test_shutdown_racing_claim_commit_releases_without_starting_handler(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    claimed, finish_claim = asyncio.Event(), asyncio.Event()
    claim = queue._claim
    calls = 0

    async def paused_claim(topic: str) -> JobMessage | None:
        result = await claim(topic)
        claimed.set()
        await finish_claim.wait()
        return result

    async def handler(_: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(queue, "_claim", paused_claim)
    try:
        await queue.publish("transcribe", {"synthetic": True})
        await queue.subscribe("transcribe", handler)
        await asyncio.wait_for(claimed.wait(), 3)
        await queue.stop_consuming()
        cancel = asyncio.create_task(queue.cancel_in_flight())
        await asyncio.sleep(0.01)
        finish_claim.set()
        await asyncio.wait_for(cancel, 3)
        assert calls == 0
        assert await queue.pending_count("transcribe") == 1
        message, = await rows(queue)
        assert message.attempts == 0 and message.locked_until is None
    finally:
        finish_claim.set()
        await queue.disconnect()


async def test_lease_deadline_cancels_slow_handler_before_another_delivery(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.infra.queue_postgres.VISIBILITY_SECONDS", 0.2)
    monkeypatch.setattr("app.infra.queue_postgres.POLL_SECONDS", 0.02)
    first, second = PostgresJobQueue(pg_url), PostgresJobQueue(pg_url)
    await first.connect()
    await second.connect()
    started, cancelled, redelivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = 0
    overlap = False

    async def slow(_: dict[str, Any]) -> None:
        nonlocal active
        active += 1
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            cancelled.set()

    async def fast(_: dict[str, Any]) -> None:
        nonlocal overlap
        overlap = active > 0
        redelivered.set()

    try:
        await first.publish("transcribe", {"synthetic": True})
        await first.subscribe("transcribe", slow)
        await asyncio.wait_for(started.wait(), 3)
        await first.stop_consuming()  # drain the running handler, but do not claim it again
        await second.subscribe("transcribe", fast)
        await asyncio.wait_for(cancelled.wait(), 3)
        await asyncio.wait_for(redelivered.wait(), 3)
        assert not overlap
        await second.stop_consuming()
        assert await second.wait_idle(3)
        assert await rows(second) == []
    finally:
        await first.disconnect()
        await second.disconnect()


@pytest.mark.parametrize("topic,override,expected", [
    ("transcribe", None, 3), ("diarize", None, 3), ("diarize", "0", 0),
    ("summarize", None, 1), ("summarize", "2", 2),
])
async def test_topic_retry_policy_matches_rabbitmq(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, topic: str, override: str | None, expected: int,
) -> None:
    env = {"transcribe": "ASR_MAX_RETRIES", "diarize": "DIARIZATION_MAX_RETRIES", "summarize": "SUMMARIZE_MAX_RETRIES"}
    monkeypatch.delenv(env[topic], raising=False)
    if override is not None:
        monkeypatch.setenv(env[topic], override)
    monkeypatch.setenv("SUMMARIZE_RETRY_DELAY_SECONDS", "0")
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    calls = 0

    async def fail(_: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise ValueError("synthetic failure")

    try:
        await queue.publish(topic, {"synthetic": True})
        await queue.subscribe(topic, fail)

        async def settled() -> bool:
            return calls > 0 and all(message.topic != topic for message in await rows(queue))

        await eventually(settled)
        assert calls == expected + 1
        assert [message.topic for message in await rows(queue)] == ([] if topic == "diarize" else [f"{topic}.failed"])
    finally:
        await queue.disconnect()


async def test_subscribed_deferral_does_not_block_the_next_message(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUEUE_DEFER_SECONDS", "0.2")
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    seen: list[int] = []
    times: list[float] = []
    next_processed, finished = asyncio.Event(), asyncio.Event()

    async def handler(message: dict[str, Any]) -> None:
        seen.append(message["index"])
        times.append(asyncio.get_running_loop().time())
        if len(seen) == 1:
            raise DeferDelivery
        if message["index"] == 1:
            next_processed.set()
        else:
            finished.set()

    try:
        await queue.publish("transcribe", {"index": 0})
        await queue.publish("transcribe", {"index": 1})
        await queue.subscribe("transcribe", handler)
        await asyncio.wait_for(next_processed.wait(), 3)
        parked = [message for message in await rows(queue) if message.body["index"] == 0]
        assert len(parked) == 1 and parked[0].attempts == 0 and parked[0].headers == {}
        await asyncio.wait_for(finished.wait(), 5)
        assert seen == [0, 1, 0]
        assert times[2] - times[0] >= 0.2
        await queue.stop_consuming()
        assert await queue.wait_idle(3)
        assert await rows(queue) == []
    finally:
        await queue.disconnect()
