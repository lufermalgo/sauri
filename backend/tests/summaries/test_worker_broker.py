"""T12/#280: real broker retry exhaustion must reach the authenticated terminal consumer."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import aio_pika
import pytest

from app.infra.models import SummaryRequestOutbox
from app.infra.queue_rabbitmq import RabbitMQJobQueue, _message_signature
from tests.summaries.test_worker import Case, outcomes

pytest_plugins = ("tests.summaries.test_worker",)  # shared disposable PG fixture


async def wait_status(case: Case, event_id: str, expected: str) -> None:
    async with asyncio.timeout(20):
        while True:
            status, _, _ = await outcomes(case, event_id)
            if status == expected:
                return
            await asyncio.sleep(0.05)


async def test_real_broker_exhaustion_marks_failed_without_losing_success(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not url:
        pytest.fail("Set SAURI_QA_RABBITMQ_URL to exclusively disposable RabbitMQ")
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "t12-synthetic-signing-key-with-more-than-32-bytes")
    monkeypatch.setenv("ASR_MAX_RETRIES", "1")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    from app.summaries import worker

    monkeypatch.setattr(worker, "create_summarization_engine", lambda: case)
    queue = RabbitMQJobQueue(url)
    await queue.connect()
    try:
        await worker.start_worker(queue, case.factory)
        await queue.publish("summarize", case.message.copy())
        first_id = case.message["event_id"]
        await wait_status(case, first_id, "succeeded")
        case.failure = True
        second = {**case.message, "event_id": str(uuid4()), "generation": 2}
        async with case.factory() as session, session.begin():
            session.add(SummaryRequestOutbox(**second, status="pending", delivered_at=datetime.now(UTC)))
        case.message = second
        # A signature for the source topic cannot authorize a terminal event.
        forged_body = json.dumps(second).encode()
        connection = await aio_pika.connect_robust(url)
        try:
            channel = await connection.channel(publisher_confirms=True)
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=forged_body,
                    headers={"x-sauri-signature": _message_signature("summarize", forged_body)},
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key="summarize.failed",
                mandatory=True,
            )
            await asyncio.sleep(0.2)
            assert (await outcomes(case, second["event_id"]))[0] == "pending"
        finally:
            await connection.close()
        await queue.publish("summarize", second)
        await wait_status(case, second["event_id"], "failed")
        first_status, first_rows, first_processed = await outcomes(case, first_id)
        second_status, second_rows, second_processed = await outcomes(case, second["event_id"])
        assert (first_status, len(first_rows), first_processed) == ("succeeded", 1, True)
        assert (second_status, second_rows, second_processed) == ("failed", [], False)
        assert len(case.engine_calls) == 3  # success, initial failure, one broker retry
    finally:
        await queue.disconnect()


@pytest.mark.parametrize("topic,expected_requeue", [("summarize", True), ("summarize.failed", True)])
async def test_terminal_delivery_is_not_discarded_on_failure(
    topic: str, expected_requeue: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "t12-synthetic-signing-key-with-more-than-32-bytes")
    monkeypatch.setenv("ASR_MAX_RETRIES", "0")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    queue = RabbitMQJobQueue("amqp://not-used/")
    channel = AsyncMock()
    broker_queue = AsyncMock()
    channel.declare_queue.return_value = broker_queue
    queue._channel = channel
    body = json.dumps({"event_id": "event"}).encode()
    message = AsyncMock()
    message.body = body
    message.headers = {"x-sauri-signature": _message_signature(topic, body)}

    async def fail_handler(_: dict[str, object]) -> None:
        raise RuntimeError("temporary database failure")

    await queue.subscribe(topic, fail_handler)
    if topic == "summarize":
        async def fail_publication(_: str, __: dict[str, object]) -> None:
            raise RuntimeError("broker did not confirm")
        monkeypatch.setattr(queue, "publish", fail_publication)
    callback = broker_queue.consume.call_args.args[0]
    await callback(message)
    message.ack.assert_not_awaited()
    message.nack.assert_awaited_once_with(requeue=expected_requeue)
