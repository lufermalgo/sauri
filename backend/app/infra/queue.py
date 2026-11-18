"""Cloud-agnostic job queue / messaging abstraction.

Defines the `JobQueue` interface with at-least-once delivery semantics,
retries, and dead-letter support. The concrete implementation is selected
via configuration (QUEUE_KIND environment variable) without
modifying business logic.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any


class DeferDelivery(Exception):  # noqa: N818 - a control signal, not an error
    """Raised by a handler that cannot run this delivery yet, but must not lose it.

    The queue parks the message for a fixed pause and delivers it again, without
    counting it as a failed attempt (a live lease held by another worker is the case).
    """


class JobQueue(ABC):
    """Abstract job queue interface with at-least-once delivery."""

    @abstractmethod
    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        """Publishes a message/job to the given topic (queue)."""
        ...

    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Subscribes a handler to consume messages from a topic.

        The handler receives the deserialized message. The implementation
        acks after the handler processes the message successfully; on
        exception, it nacks without requeue (dead-lettering if configured).
        """
        ...

    async def stop_consuming(self) -> None:  # noqa: B027 - optional hook; brokers without consumers need nothing
        """Stop taking new deliveries; handlers already running keep going."""

    async def wait_idle(self, timeout_s: float) -> bool:
        """Wait until no handler is running; False when ``timeout_s`` elapsed first."""
        return True

    async def cancel_in_flight(self) -> None:  # noqa: B027 - optional hook
        """Cancel the running handlers and give their deliveries back to the broker."""

    async def pending_count(self, topic: str) -> int | None:
        """Messages waiting (not yet delivered) in ``topic``; None when unknown."""
        return None

    @abstractmethod
    async def connect(self) -> None:
        """Establishes the connection with the broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Closes the connection with the broker."""
        ...


def create_job_queue() -> JobQueue:
    """Factory that creates the configured JobQueue implementation.

    RabbitMQ remains the default; PostgreSQL uses the application database.
    """
    kind = os.environ.get("QUEUE_KIND", "rabbitmq")
    if kind == "postgres":
        from app.infra.queue_postgres import PostgresJobQueue

        return PostgresJobQueue()
    if kind != "rabbitmq":
        raise ValueError(f"Unsupported QUEUE_KIND: {kind}")

    from app.infra.queue_rabbitmq import RabbitMQJobQueue
    from app.infra.secrets import SecretUnavailableError, read_secret, require_url_password, with_password

    broker_url = os.environ.get("QUEUE_BROKER_URL")
    if not broker_url:
        raise SecretUnavailableError("Set QUEUE_BROKER_URL (the password goes in QUEUE_BROKER_PASSWORD_FILE)")
    broker_url = with_password(broker_url, read_secret("QUEUE_BROKER_PASSWORD_FILE"))
    require_url_password(broker_url, "QUEUE_BROKER_PASSWORD_FILE", "QUEUE_BROKER_URL")
    return RabbitMQJobQueue(broker_url=broker_url)
