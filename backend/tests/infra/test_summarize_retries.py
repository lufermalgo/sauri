"""#1045: `summarize` retries once, after a fixed delay parked in a broker-side queue."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pamqp.commands import Basic

from app.infra.queue_rabbitmq import RabbitMQJobQueue, _message_signature, _read_max_retries, _read_retry_delay

KEY = "synthetic-signing-key-with-at-least-32-bytes"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ASR_MAX_RETRIES", "DIARIZATION_MAX_RETRIES", "SUMMARIZE_MAX_RETRIES", "SUMMARIZE_RETRY_DELAY_SECONDS",
        "QUEUE_DLX_EXCHANGE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", KEY)


def test_summarize_defaults_to_one_retry_without_changing_other_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _read_max_retries("summarize") == 1
    assert _read_max_retries("transcribe") == 3 and _read_max_retries("diarize") == 3
    monkeypatch.setenv("ASR_MAX_RETRIES", "7")  # the shared ASR setting no longer governs summaries
    assert _read_max_retries("summarize") == 1 and _read_max_retries("transcribe") == 7


@pytest.mark.parametrize("raw,expected", [("0", 0), ("4", 4), ("10", 10), ("11", 1), ("-1", 1), ("x", 1), ("", 1)])
def test_summarize_max_retries_is_read_from_its_own_variable(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int,
) -> None:
    monkeypatch.setenv("SUMMARIZE_MAX_RETRIES", raw)
    assert _read_max_retries("summarize") == expected


@pytest.mark.parametrize("raw,expected", [
    (None, 30.0), ("", 30.0), ("0", 0.0), ("45", 45.0), ("2.5", 2.5), ("3600", 3600.0),
    ("-1", 30.0), ("3601", 30.0), ("abc", 30.0), ("nan", 30.0), ("inf", 30.0),
])
def test_summarize_retry_delay_configuration(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float) -> None:
    if raw is not None:
        monkeypatch.setenv("SUMMARIZE_RETRY_DELAY_SECONDS", raw)
    assert _read_retry_delay("summarize") == expected


@pytest.mark.parametrize("topic", ["transcribe", "diarize", "summarize.failed", "transcribe.failed"])
def test_other_topics_retry_immediately(monkeypatch: pytest.MonkeyPatch, topic: str) -> None:
    monkeypatch.setenv("SUMMARIZE_RETRY_DELAY_SECONDS", "99")
    assert _read_retry_delay(topic) == 0.0


async def failing_delivery(topic: str) -> tuple[AsyncMock, AsyncMock]:
    queue = RabbitMQJobQueue("amqp://unused/")
    channel = AsyncMock()
    channel.is_closed = False
    channel.default_exchange.publish.return_value = Basic.Ack()
    queue._channel = channel
    await queue.subscribe(topic, AsyncMock(side_effect=RuntimeError("synthetic error")))
    callback = channel.declare_queue.return_value.consume.await_args.args[0]
    message = AsyncMock()
    message.channel = MagicMock(is_closed=False)
    message.body = json.dumps({"event_id": "synthetic"}).encode()
    message.headers = {"x-sauri-signature": _message_signature(topic, message.body)}
    message.content_type = "application/json"
    channel.declare_queue.reset_mock()
    await callback(message)
    return channel, message


async def test_summarize_retry_is_parked_in_a_delay_queue_that_returns_to_the_topic() -> None:
    channel, message = await failing_delivery("summarize")
    channel.declare_queue.assert_awaited_once_with("summarize.retry", durable=True, arguments={
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "summarize",
    })
    publish = channel.default_exchange.publish
    publish.assert_awaited_once()
    assert publish.await_args.kwargs == {"routing_key": "summarize.retry", "mandatory": True}
    retry = publish.await_args.args[0]
    assert retry.expiration == 30
    assert retry.headers["x-sauri-retries"] == 1
    assert retry.headers["x-sauri-signature"] == _message_signature("summarize", message.body, 1)
    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()


async def test_zero_delay_republishes_straight_to_the_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMARIZE_RETRY_DELAY_SECONDS", "0")
    channel, message = await failing_delivery("summarize")
    channel.declare_queue.assert_not_awaited()
    assert channel.default_exchange.publish.await_args.kwargs["routing_key"] == "summarize"
    assert channel.default_exchange.publish.await_args.args[0].expiration is None
    message.ack.assert_awaited_once()


async def test_transcription_retry_path_is_unchanged() -> None:
    channel, message = await failing_delivery("transcribe")
    channel.declare_queue.assert_not_awaited()
    assert channel.default_exchange.publish.await_args.kwargs["routing_key"] == "transcribe"
    assert channel.default_exchange.publish.await_args.args[0].expiration is None
    message.ack.assert_awaited_once()


async def test_unconfirmed_delayed_publication_keeps_the_original_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = RabbitMQJobQueue("amqp://unused/")
    channel = AsyncMock()
    channel.is_closed = False
    channel.default_exchange.publish.return_value = Basic.Nack()
    queue._channel = channel
    await queue.subscribe("summarize", AsyncMock(side_effect=RuntimeError("synthetic error")))
    callback = channel.declare_queue.return_value.consume.await_args.args[0]
    message = AsyncMock()
    message.channel = MagicMock(is_closed=False)
    message.body = b"{}"
    message.headers = {"x-sauri-signature": _message_signature("summarize", message.body)}
    await callback(message)
    message.ack.assert_not_awaited()
    message.nack.assert_awaited_once_with(requeue=True)
