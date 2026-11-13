"""JobQueue implementation using RabbitMQ via aio-pika.

Provides at-least-once delivery, persistent messages (delivery_mode=2),
retries bounded by ASR_MAX_RETRIES with counting via a custom header
(x-sauri-retries), and automatic dead-lettering once retries are
exhausted (nack without requeue).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from pamqp.commands import Basic

from app.infra.queue import JobQueue

logger = logging.getLogger(__name__)

_MAX_RETRIES_MIN = 0
_MAX_RETRIES_MAX = 10
_MAX_RETRIES_DEFAULT = 3

# Map of topic → environment variable for retries
_TOPIC_TO_ENV_RETRIES: dict[str, str] = {
    "transcribe": "ASR_MAX_RETRIES",
    "diarize": "DIARIZATION_MAX_RETRIES",
}


def _read_max_retries(topic: str = "transcribe") -> int:
    """Reads the retries environment variable for the given topic.

    Topic map:
    - "transcribe" → ASR_MAX_RETRIES
    - "diarize" → DIARIZATION_MAX_RETRIES

    Valid range: 0-10. Default: 3.
    """
    env_var = _TOPIC_TO_ENV_RETRIES.get(topic, "ASR_MAX_RETRIES")
    raw = os.environ.get(env_var, "")
    if not raw.strip():
        return _MAX_RETRIES_DEFAULT
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "%s='%s' is not a valid integer. Using default %d.",
            env_var,
            raw,
            _MAX_RETRIES_DEFAULT,
        )
        return _MAX_RETRIES_DEFAULT
    if value < _MAX_RETRIES_MIN or value > _MAX_RETRIES_MAX:
        logger.warning(
            "%s=%d out of range [%d, %d]. Using default %d.",
            env_var,
            value,
            _MAX_RETRIES_MIN,
            _MAX_RETRIES_MAX,
            _MAX_RETRIES_DEFAULT,
        )
        return _MAX_RETRIES_DEFAULT
    return value


_HEADER_RETRIES = "x-sauri-retries"
_HEADER_SIGNATURE = "x-sauri-signature"
_SIGNING_KEY_ENV = "QUEUE_MESSAGE_SIGNING_KEY"


def _signing_key() -> bytes:
    value = os.environ.get(_SIGNING_KEY_ENV, "")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError(f"{_SIGNING_KEY_ENV} must contain at least 32 bytes")
    return value.encode("utf-8")


def _message_signature(topic: str, body: bytes, retries: int = 0) -> str:
    signed_data = topic.encode("utf-8") + b"\0" + str(retries).encode("ascii") + b"\0" + body
    return hmac.new(_signing_key(), signed_data, hashlib.sha256).hexdigest()


def _has_valid_signature(topic: str, body: bytes, headers: dict[str, Any] | None) -> bool:
    message_headers = headers or {}
    signature = message_headers.get(_HEADER_SIGNATURE)
    retries = message_headers.get(_HEADER_RETRIES, 0)
    return (
        isinstance(signature, str)
        and type(retries) is int
        and retries >= 0
        and hmac.compare_digest(signature, _message_signature(topic, body, retries))
    )


def _count_retries(message: aio_pika.abc.AbstractIncomingMessage) -> int:
    """Counts the accumulated retries of a message using a custom header.

    RabbitMQ's x-death header can't be used for this: it's only populated
    by RabbitMQ when a message passes through a real dead-letter-exchange.
    Without a DLX configured (QUEUE_DLX_EXCHANGE empty, the default case),
    a direct nack(requeue=True) requeues the same message without leaving
    any trace, so _count_retries would always return 0 and the message
    would be retried forever. That's why the count is tracked explicitly
    in the x-sauri-retries header, which this module increments each time
    it republishes a retry.
    """
    headers = message.headers or {}
    count = headers.get(_HEADER_RETRIES, 0)
    return count if isinstance(count, int) else 0


def _read_dlx_exchange() -> str | None:
    """Reads QUEUE_DLX_EXCHANGE from the environment. Returns None if unset or empty."""
    raw = os.environ.get("QUEUE_DLX_EXCHANGE", "")
    return raw.strip() if raw.strip() else None


class RabbitMQJobQueue(JobQueue):
    """RabbitMQ (aio-pika) implementation of JobQueue."""

    def __init__(self, broker_url: str) -> None:
        self._broker_url = broker_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._dlx_exchange: str | None = _read_dlx_exchange()

    async def connect(self) -> None:
        """Creates a robust connection and a channel with the RabbitMQ broker."""
        self._connection = await aio_pika.connect_robust(self._broker_url)
        self._channel = await self._connection.channel(publisher_confirms=True, on_return_raises=True)
        logger.info("RabbitMQ connection established")

    async def disconnect(self) -> None:
        """Closes the channel and connection with RabbitMQ."""
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._channel = None
        self._connection = None
        logger.info("RabbitMQ connection closed.")

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        """Publishes a persistent JSON message to the durable `topic` queue."""
        if self._channel is None:
            raise RuntimeError("No active connection. Call `connect()` first.")

        queue = await self._channel.declare_queue(topic, durable=True)
        body = json.dumps(message).encode("utf-8")
        amqp_message = Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            headers={_HEADER_SIGNATURE: _message_signature(topic, body)},
        )
        confirmation = await self._channel.default_exchange.publish(
            amqp_message,
            routing_key=queue.name,
            mandatory=True,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("Broker did not confirm publication")
        logger.debug("Message published to '%s' with broker confirmation", topic)

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Consumes messages from the `topic` queue, invokes the handler and ack/nack.

        - Acks after the handler processes the message successfully.
        - If accumulated retries < max_retries for the topic: republishes a
          copy of the message with x-sauri-retries incremented and acks the
          original (see _count_retries for why nack(requeue=True) isn't used
          here).
        - Nacks with requeue=False once max_retries is reached (routes to
          dead-letter if the queue has a DLX configured; otherwise it's
          discarded).
        """
        if self._channel is None:
            raise RuntimeError("No active connection. Call `connect()` first.")
        _signing_key()
        channel = self._channel

        max_retries = _read_max_retries(topic)

        queue_arguments: dict[str, Any] = {}
        if self._dlx_exchange:
            queue_arguments["x-dead-letter-exchange"] = self._dlx_exchange

        queue = await channel.declare_queue(
            topic, durable=True, arguments=queue_arguments or None
        )

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            if not _has_valid_signature(topic, message.body, message.headers):
                logger.error("Unauthenticated message rejected on '%s'.", topic)
                await message.nack(requeue=False)
                return
            try:
                payload: dict[str, Any] = json.loads(message.body.decode("utf-8"))
                await handler(payload)
                await message.ack()
                logger.debug("Message processed and acked on '%s'.", topic)
            except Exception:
                retries = _count_retries(message)
                if retries < max_retries:
                    logger.warning(
                        "Error processing message on '%s'. Retry %d/%d. Requeueing.",
                        topic,
                        retries + 1,
                        max_retries,
                    )
                    retry_headers = {
                        **(message.headers or {}),
                        _HEADER_RETRIES: retries + 1,
                    }
                    retry_headers[_HEADER_SIGNATURE] = _message_signature(
                        topic, message.body, retries + 1
                    )
                    retry_message = Message(
                        body=message.body,
                        delivery_mode=DeliveryMode.PERSISTENT,
                        content_type=message.content_type,
                        headers=retry_headers,
                    )
                    await channel.default_exchange.publish(retry_message, routing_key=topic)
                    await message.ack()
                else:
                    if self._dlx_exchange:
                        logger.error(
                            "Error processing message on '%s'. Retries exhausted (%d/%d). "
                            "Routing to dead-letter (DLX='%s').",
                            topic,
                            retries,
                            max_retries,
                            self._dlx_exchange,
                        )
                    else:
                        logger.error(
                            "Error processing message on '%s'. Retries exhausted (%d/%d). "
                            "Message discarded (no DLX configured).",
                            topic,
                            retries,
                            max_retries,
                        )
                    await message.nack(requeue=False)

        await queue.consume(_on_message)
        logger.info("Subscribed to queue '%s'. Max retries: %d.", topic, max_retries)
