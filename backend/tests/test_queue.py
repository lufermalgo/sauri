"""Tests for the JobQueue (queue_rabbitmq.py).

# Feature: transcription-asr
Tasks: 10.3, 10.4
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aio_pika.abc import AbstractIncomingMessage
from pamqp.commands import Basic

from app.infra.queue_rabbitmq import (
    RabbitMQJobQueue,
    _count_retries,
    _has_valid_signature,
    _message_signature,
    _read_max_retries,
)


@pytest.fixture(autouse=True)
def queue_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-key-0123456789abcdef")


def _signed_headers(topic: str, body: bytes, retries: int | None = None) -> dict[str, Any]:
    headers: dict[str, Any] = {
        "x-sauri-signature": _message_signature(topic, body, retries or 0)
    }
    if retries is not None:
        headers["x-sauri-retries"] = retries
    return headers

# ---------------------------------------------------------------------------
# Example-based tests — ASR_MAX_RETRIES range validation (Task 10.3)
# Validates: Requirements 9.2
# ---------------------------------------------------------------------------


class TestMaxRetries:
    """Tests for ASR_MAX_RETRIES range validation."""

    def test_default_when_absent(self) -> None:
        """ASR_MAX_RETRIES absent → default 3."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASR_MAX_RETRIES", None)
            assert _read_max_retries() == 3

    def test_default_when_empty(self) -> None:
        """ASR_MAX_RETRIES empty → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": ""}, clear=False):
            assert _read_max_retries() == 3

    def test_valid_value_0(self) -> None:
        """ASR_MAX_RETRIES=0 → 0 (no retries)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "0"}, clear=False):
            assert _read_max_retries() == 0

    def test_valid_value_10(self) -> None:
        """ASR_MAX_RETRIES=10 → 10 (max allowed)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "10"}, clear=False):
            assert _read_max_retries() == 10

    def test_valid_value_5(self) -> None:
        """ASR_MAX_RETRIES=5 → 5."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "5"}, clear=False):
            assert _read_max_retries() == 5

    def test_out_of_range_negative(self) -> None:
        """ASR_MAX_RETRIES=-1 → default 3 (out of range)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "-1"}, clear=False):
            assert _read_max_retries() == 3

    def test_out_of_range_greater_than_10(self) -> None:
        """ASR_MAX_RETRIES=11 → default 3 (out of range)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "11"}, clear=False):
            assert _read_max_retries() == 3

    def test_out_of_range_100(self) -> None:
        """ASR_MAX_RETRIES=100 → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "100"}, clear=False):
            assert _read_max_retries() == 3

    def test_not_an_integer(self) -> None:
        """ASR_MAX_RETRIES='abc' → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "abc"}, clear=False):
            assert _read_max_retries() == 3


# ---------------------------------------------------------------------------
# Queue integration tests (Task 10.4)
# Validates: Requirements 1.5, 1.6, 1.7, 9.2, 9.3, 9.4
# ---------------------------------------------------------------------------


class TestCountRetries:
    """Unit tests for _count_retries (no real RabbitMQ needed).

    The count is tracked with a custom header (x-sauri-retries), not with
    RabbitMQ's x-death: x-death is only populated by RabbitMQ when a message
    passes through a real dead-letter-exchange, and in this environment
    (without QUEUE_DLX_EXCHANGE configured) a direct nack(requeue=True)
    never touches it — which caused an infinite retry loop, since
    _count_retries always saw 0.
    """

    def test_no_header_returns_0(self) -> None:
        """Message without x-sauri-retries → 0 retries."""
        msg = MagicMock()
        msg.headers = {}
        assert _count_retries(msg) == 0

    def test_no_headers_returns_0(self) -> None:
        """Message without headers → 0 retries."""
        msg = MagicMock()
        msg.headers = None
        assert _count_retries(msg) == 0

    def test_header_with_value_1(self) -> None:
        """x-sauri-retries=1 → 1 retry."""
        msg = MagicMock()
        msg.headers = {"x-sauri-retries": 1}
        assert _count_retries(msg) == 1

    def test_header_with_value_3(self) -> None:
        """x-sauri-retries=3 → 3 retries."""
        msg = MagicMock()
        msg.headers = {"x-sauri-retries": 3}
        assert _count_retries(msg) == 3

    def test_header_non_integer_returns_0(self) -> None:
        """x-sauri-retries with a non-integer value → 0 retries."""
        msg = MagicMock()
        msg.headers = {"x-sauri-retries": "not-an-integer"}
        assert _count_retries(msg) == 0


class TestRabbitMQJobQueueBehavior:
    @pytest.mark.asyncio
    async def test_publish_signs_topic_and_exact_body(self) -> None:
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._channel = AsyncMock()
        queue._channel.declare_queue.return_value.name = "transcribe"
        queue._channel.default_exchange.publish.return_value = Basic.Ack(delivery_tag=1)
        await queue.publish("transcribe", {"meeting_id": "synthetic-meeting"})

        args, kwargs = queue._channel.default_exchange.publish.call_args
        published = args[0]
        assert kwargs["routing_key"] == "transcribe"
        assert kwargs["mandatory"] is True
        assert _has_valid_signature("transcribe", published.body, published.headers)
        assert not _has_valid_signature(
            "diarize", published.body, published.headers
        )
        assert not _has_valid_signature(
            "transcribe", published.body + b"tampered", published.headers
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirmation", [None, Basic.Nack(delivery_tag=1)])
    async def test_unconfirmed_publish_fails(self, confirmation: object) -> None:
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._channel = AsyncMock()
        queue._channel.declare_queue.return_value.name = "summarize"
        queue._channel.default_exchange.publish.return_value = confirmation
        with pytest.raises(RuntimeError, match="did not confirm"):
            await queue.publish("summarize", {"event_id": "synthetic"})

    def test_retry_counter_is_authenticated_by_signature(self) -> None:
        body = json.dumps({"meeting_id": "synthetic-meeting"}).encode()
        headers = _signed_headers("transcribe", body, retries=0)
        assert _has_valid_signature("transcribe", body, headers)

        headers["x-sauri-retries"] = 3
        assert not _has_valid_signature("transcribe", body, headers)

    @pytest.mark.asyncio
    async def test_rejects_signature_when_topic_differs(self) -> None:
        """A message authenticated for one topic cannot be replayed on another."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        handler = AsyncMock()
        body = json.dumps({"meeting_id": "synthetic-meeting"}).encode()
        mock_message = AsyncMock()
        mock_message.body = body
        mock_message.headers = _signed_headers("transcribe", body)
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()
        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue
        captured_callback = None

        async def capture_consume(callback: Any) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume
        await queue.subscribe("diarize", handler)
        assert captured_callback is not None
        await captured_callback(mock_message)

        handler.assert_not_awaited()
        mock_message.nack.assert_called_once_with(requeue=False)

    """Consumer behavior tests (aio-pika mocked).

    Verifies ack/nack/requeue logic without a real RabbitMQ connection.
    """

    @pytest.mark.asyncio
    async def test_rejects_unsigned_message_before_handler(self) -> None:
        """Unsigned queue payloads must not reach processing handlers."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = None
        handler = AsyncMock()
        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "victim"}).encode()
        mock_message.headers = {}
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()
        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue
        captured_callback = None

        async def capture_consume(callback: Any) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume
        with patch.dict(os.environ, {"QUEUE_MESSAGE_SIGNING_KEY": "synthetic-test-key-0123456789abcdef"}):
            await queue.subscribe("transcribe", handler)
            assert captured_callback is not None
            await captured_callback(mock_message)

        handler.assert_not_awaited()
        mock_message.nack.assert_called_once_with(requeue=False)

    @pytest.mark.asyncio
    async def test_ack_on_success(self) -> None:
        """Req 1.5: Successful processing → ack."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = None

        handler_called = False

        async def mock_handler(msg: dict[str, Any]) -> None:
            nonlocal handler_called
            handler_called = True

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "abc", "audio_ref": "x"}).encode()
        mock_message.headers = _signed_headers("transcribe", mock_message.body)
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue

        captured_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] | None = None

        async def capture_consume(callback: Callable[[AbstractIncomingMessage], Awaitable[None]]) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await queue.subscribe("transcribe", mock_handler)
        assert captured_callback is not None
        await captured_callback(mock_message)

        assert handler_called
        mock_message.ack.assert_called_once()
        mock_message.nack.assert_not_called()

    @pytest.mark.asyncio
    async def test_nack_without_requeue_on_exception_retries_exhausted(self) -> None:
        """Req 1.6: Exception with retries exhausted → nack(requeue=False)."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = "dlx-exchange"

        async def failing_handler(msg: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "abc"}).encode()
        mock_message.headers = _signed_headers("transcribe", mock_message.body, retries=3)
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue

        captured_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] | None = None

        async def capture_consume(callback: Callable[[AbstractIncomingMessage], Awaitable[None]]) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await queue.subscribe("transcribe", failing_handler)
        assert captured_callback is not None
        await captured_callback(mock_message)

        mock_message.nack.assert_called_once_with(requeue=False)
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_republishes_with_retries_incremented_on_exception_retries_available(self) -> None:
        """Req 9.2: Exception with retries available → republish with counter +1 and ack the original.

        Doesn't use nack(requeue=True): without a DLX configured that requeues
        the same message without leaving a trace in x-death, causing an
        infinite loop of identical retries (a real bug observed in
        production). Instead, a copy is published with x-sauri-retries
        incremented and the original message is acked.
        """
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = None

        async def failing_handler(msg: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "abc"}).encode()
        mock_message.headers = _signed_headers("transcribe", mock_message.body, retries=1)
        mock_message.content_type = "application/json"
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue
        queue._channel.default_exchange.publish = AsyncMock()

        captured_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] | None = None

        async def capture_consume(callback: Callable[[AbstractIncomingMessage], Awaitable[None]]) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await queue.subscribe("transcribe", failing_handler)
        assert captured_callback is not None
        await captured_callback(mock_message)

        mock_message.nack.assert_not_called()
        mock_message.ack.assert_called_once()
        queue._channel.default_exchange.publish.assert_called_once()
        published_message, kwargs = queue._channel.default_exchange.publish.call_args
        assert kwargs["routing_key"] == "transcribe"
        assert published_message[0].headers["x-sauri-retries"] == 2
        assert _has_valid_signature(
            "transcribe", published_message[0].body, published_message[0].headers
        )

    @pytest.mark.asyncio
    async def test_dlx_configured_in_queue_arguments(self) -> None:
        """Req 1.7, 9.3: DLX configured → x-dead-letter-exchange is passed."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = "my-dlx"

        async def noop_handler(msg: dict[str, Any]) -> None:
            pass

        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue
        mock_queue.consume = AsyncMock()

        await queue.subscribe("transcribe", noop_handler)

        # Check declare_queue was called with DLX argument
        call_kwargs = queue._channel.declare_queue.call_args[1]
        arguments = call_kwargs.get("arguments")
        assert arguments is not None
        assert arguments.get("x-dead-letter-exchange") == "my-dlx"

    @pytest.mark.asyncio
    async def test_discard_without_dlx(self) -> None:
        """Req 9.4: No DLX + retries exhausted → discard (nack requeue=False)."""
        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = None

        async def failing_handler(msg: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "abc"}).encode()
        mock_message.headers = _signed_headers("transcribe", mock_message.body, retries=2)
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        queue._channel = AsyncMock()
        mock_queue = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue

        captured_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] | None = None

        async def capture_consume(callback: Callable[[AbstractIncomingMessage], Awaitable[None]]) -> None:
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        with patch("app.infra.queue_rabbitmq._read_max_retries", return_value=2):
            await queue.subscribe("transcribe", failing_handler)
        assert captured_callback is not None
        await captured_callback(mock_message)

        mock_message.nack.assert_called_once_with(requeue=False)
