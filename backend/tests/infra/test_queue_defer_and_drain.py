"""A deferred delivery is parked, not counted or lost; a stopping worker drains or hands jobs back (#1166)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pamqp.commands import Basic

from app.infra.queue import DeferDelivery
from app.infra.queue_rabbitmq import RabbitMQJobQueue, _message_signature
from app.worker import shutdown_grace_seconds, stop_gracefully

pytestmark = pytest.mark.asyncio


class FakeQueue:
    def __init__(self) -> None:
        self.callback: Callable[[Any], Awaitable[None]] | None = None
        self.cancelled: list[str] = []

    async def consume(self, callback: Callable[[Any], Awaitable[None]]) -> str:
        self.callback = callback
        return "consumer-1"

    async def cancel(self, tag: str) -> None:
        self.cancelled.append(tag)


class FakeChannel:
    is_closed = False

    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []
        self.declared: dict[str, dict[str, Any] | None] = {}
        self.queue = FakeQueue()
        self.default_exchange = self

    async def set_qos(self, **kwargs: object) -> None: ...

    async def declare_queue(self, name: str, durable: bool = True, arguments: dict[str, Any] | None = None) -> Any:
        self.declared[name] = arguments
        return self.queue

    async def publish(self, message: Any, routing_key: str, mandatory: bool = False) -> Basic.Ack:
        self.published.append((routing_key, message))
        return Basic.Ack()


def _incoming(channel: FakeChannel, topic: str = "transcribe", retries: int | None = None) -> AsyncMock:
    body = json.dumps({"meeting_id": "m1"}).encode()
    headers: dict[str, Any] = {"x-sauri-signature": _message_signature(topic, body, retries or 0)}
    if retries is not None:
        headers["x-sauri-retries"] = retries
    message = AsyncMock()
    message.body, message.headers, message.content_type, message.channel = body, headers, "application/json", channel
    return message


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-key-0123456789abcdef")
    monkeypatch.setenv("QUEUE_DEFER_SECONDS", "7")


async def _subscribed(handler: Callable[[dict[str, Any]], Awaitable[None]]) -> tuple[RabbitMQJobQueue, FakeChannel]:
    queue = RabbitMQJobQueue("amqp://unused")
    channel = FakeChannel()
    queue._channel = channel  # type: ignore[assignment]
    await queue.subscribe("transcribe", handler)
    return queue, channel


async def test_deferred_delivery_is_parked_for_a_fixed_pause_without_counting_a_retry() -> None:
    async def busy(message: dict[str, Any]) -> None:
        raise DeferDelivery

    _, channel = await _subscribed(busy)
    incoming = _incoming(channel, retries=2)
    assert channel.queue.callback is not None

    await channel.queue.callback(incoming)

    [(routing_key, copy)] = channel.published
    assert routing_key == "transcribe.defer"
    assert channel.declared["transcribe.defer"] == {
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "transcribe",
    }
    assert copy.expiration == 7
    # Same signed headers: the retry count did not move, so the copy is still authentic and still has its retries.
    assert copy.headers == incoming.headers
    incoming.ack.assert_awaited_once()
    incoming.nack.assert_not_awaited()


async def test_deferral_that_cannot_be_parked_gives_the_delivery_back_to_the_broker() -> None:
    async def busy(message: dict[str, Any]) -> None:
        raise DeferDelivery

    _, channel = await _subscribed(busy)

    async def refused(*args: object, **kwargs: object) -> None:
        raise ConnectionError

    channel.publish = refused  # type: ignore[method-assign]
    incoming = _incoming(channel)
    assert channel.queue.callback is not None
    await channel.queue.callback(incoming)

    incoming.nack.assert_awaited_once_with(requeue=True)
    incoming.ack.assert_not_awaited()


async def test_failures_still_retry_with_the_counter_incremented() -> None:
    async def failing(message: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    _, channel = await _subscribed(failing)
    incoming = _incoming(channel, retries=1)
    assert channel.queue.callback is not None
    await channel.queue.callback(incoming)

    [(routing_key, copy)] = channel.published
    assert routing_key == "transcribe" and copy.headers["x-sauri-retries"] == 2
    incoming.ack.assert_awaited_once()


async def test_stopping_cancels_consumers_and_waits_for_the_running_job() -> None:
    release = asyncio.Event()

    async def slow(message: dict[str, Any]) -> None:
        await release.wait()

    queue, channel = await _subscribed(slow)
    incoming = _incoming(channel)
    assert channel.queue.callback is not None
    delivery = asyncio.create_task(channel.queue.callback(incoming))
    await asyncio.sleep(0.01)

    await queue.stop_consuming()
    assert channel.queue.cancelled == ["consumer-1"]
    assert not await queue.wait_idle(0.05)  # still running

    release.set()
    assert await queue.wait_idle(1)
    await delivery
    incoming.ack.assert_awaited_once()


async def test_a_job_that_outlives_the_grace_is_cancelled_and_its_delivery_requeued() -> None:
    cancelled = asyncio.Event()

    async def stuck(message: dict[str, Any]) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    queue, channel = await _subscribed(stuck)
    incoming = _incoming(channel)
    assert channel.queue.callback is not None
    delivery = asyncio.create_task(channel.queue.callback(incoming))
    await asyncio.sleep(0.01)

    assert await stop_gracefully(queue, 0.05) is False

    assert cancelled.is_set() and delivery.done()
    incoming.nack.assert_awaited_once_with(requeue=True)
    incoming.ack.assert_not_awaited()
    assert await queue.wait_idle(0)


async def test_a_job_that_finishes_within_the_grace_is_acknowledged_not_requeued() -> None:
    async def quick(message: dict[str, Any]) -> None:
        await asyncio.sleep(0.05)

    queue, channel = await _subscribed(quick)
    incoming = _incoming(channel)
    assert channel.queue.callback is not None
    delivery = asyncio.create_task(channel.queue.callback(incoming))
    await asyncio.sleep(0.01)

    assert await stop_gracefully(queue, 5) is True
    await delivery
    incoming.ack.assert_awaited_once()
    incoming.nack.assert_not_awaited()


async def test_shutdown_grace_setting_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKER_SHUTDOWN_GRACE_SECONDS", raising=False)
    assert shutdown_grace_seconds() == 540
    monkeypatch.setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "0")
    assert shutdown_grace_seconds() == 0
    monkeypatch.setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "-3")
    assert shutdown_grace_seconds() == 540
    monkeypatch.setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "later")
    assert shutdown_grace_seconds() == 540
