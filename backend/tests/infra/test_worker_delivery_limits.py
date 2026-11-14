"""Broker delivery bounds and confirm-before-ack regression tests."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pamqp.commands import Basic

from app.infra.queue_rabbitmq import RabbitMQJobQueue, _message_signature


@pytest.mark.parametrize("confirmation", [Basic.Ack(), Basic.Nack(), None])
async def test_retry_ack_requires_broker_confirmation(confirmation, monkeypatch):
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-signing-key-with-at-least-32-bytes")
    monkeypatch.setenv("ASR_MAX_RETRIES", "1")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    queue = RabbitMQJobQueue("amqp://unused/")
    channel = AsyncMock()
    channel.is_closed = False
    channel.default_exchange.publish.return_value = confirmation
    queue._channel = channel
    handler = AsyncMock(side_effect=RuntimeError("synthetic error"))
    await queue.subscribe("transcribe", handler)
    channel.set_qos.assert_awaited_once_with(prefetch_count=1, global_=False)
    callback = channel.declare_queue.return_value.consume.await_args.args[0]
    message = AsyncMock()
    message.channel = MagicMock(is_closed=False)
    message.body = json.dumps({"meeting_id": "synthetic"}).encode()
    message.headers = {"x-sauri-signature": _message_signature("transcribe", message.body)}
    await callback(message)
    if isinstance(confirmation, Basic.Ack):
        message.ack.assert_awaited_once()
        message.nack.assert_not_awaited()
    else:
        message.ack.assert_not_awaited()
        message.nack.assert_awaited_once_with(requeue=True)
    assert channel.default_exchange.publish.await_args.kwargs["mandatory"] is True
