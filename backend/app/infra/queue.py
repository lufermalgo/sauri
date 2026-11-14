"""Cloud-agnostic job queue / messaging abstraction.

Defines the `JobQueue` interface with at-least-once delivery semantics,
retries, and dead-letter support. The concrete implementation is selected
via configuration (QUEUE_BROKER_URL environment variable) without
modifying business logic.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any


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

    Reads QUEUE_BROKER_URL from the environment to determine the broker URL.
    """
    from app.infra.queue_rabbitmq import RabbitMQJobQueue
    from app.infra.secrets import read_secret, with_password

    broker_url = os.environ.get("QUEUE_BROKER_URL", "amqp://guest:guest@localhost:5672/")
    broker_url = with_password(broker_url, read_secret("QUEUE_BROKER_PASSWORD_FILE"))
    return RabbitMQJobQueue(broker_url=broker_url)
