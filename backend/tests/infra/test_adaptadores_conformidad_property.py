"""Property test for infrastructure adapter conformance (contract testing).

# Feature: meeting-capture-transcription, Property 13: Infrastructure adapter conformance
Task: 7.3 — Validates: Requirements 8.3, 8.4

Exercises the same observable contract against multiple conforming
implementations of `ObjectStore` and `JobQueue` (without depending on a live
MinIO/RabbitMQ, covered by integration test 17.3). Any real implementation
(S3/MinIO, RabbitMQ) must satisfy the same contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.infra.object_store import ObjectStore
from app.infra.queue import JobQueue


class _InMemoryStore(ObjectStore):
    """First conforming implementation: in-memory dict."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        self._objects[key] = content
        return key

    async def get(self, reference: str) -> bytes:
        return self._objects[reference]

    async def delete(self, reference: str) -> None:
        self._objects.pop(reference, None)

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        return f"memory://{reference}?ttl={ttl_seconds}"


class _IndexedListStore(ObjectStore):
    """Second conforming implementation: indexed list (different internal structure)."""

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._values: list[bytes] = []

    def _index(self, reference: str) -> int:
        return self._keys.index(reference)

    async def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        if key in self._keys:
            self._values[self._index(key)] = content
        else:
            self._keys.append(key)
            self._values.append(content)
        return key

    async def get(self, reference: str) -> bytes:
        return self._values[self._index(reference)]

    async def delete(self, reference: str) -> None:
        if reference in self._keys:
            i = self._index(reference)
            del self._keys[i]
            del self._values[i]

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        return f"list://{reference}?ttl={ttl_seconds}"


OBJECT_STORE_IMPLEMENTATIONS = [_InMemoryStore, _IndexedListStore]


class _InMemoryQueue(JobQueue):
    """Conforming JobQueue implementation: immediate in-memory delivery."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Awaitable[None]]]] = {}
        self.delivered: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        for handler in self._subscribers.get(topic, []):
            await handler(message)
            self.delivered.append((topic, message))

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None


class _BufferedQueue(JobQueue):
    """Second conforming implementation: retains published messages without a
    subscriber and delivers them as soon as one arrives, in addition to live
    delivery to active subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Awaitable[None]]]] = {}
        self._buffer: dict[str, list[dict[str, Any]]] = {}
        self.delivered: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        handlers = self._subscribers.get(topic)
        if handlers:
            for handler in handlers:
                await handler(message)
                self.delivered.append((topic, message))
        else:
            self._buffer.setdefault(topic, []).append(message)

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._subscribers.setdefault(topic, []).append(handler)
        for message in self._buffer.get(topic, []):
            await handler(message)
            self.delivered.append((topic, message))
        self._buffer[topic] = []

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None


QUEUE_IMPLEMENTATIONS = [_InMemoryQueue, _BufferedQueue]


# ---------------------------------------------------------------------------
# Property 13: Infrastructure adapter conformance
# Feature: meeting-capture-transcription, Property 13: Infrastructure adapter conformance
# Validates: Requirements 8.3, 8.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(OBJECT_STORE_IMPLEMENTATIONS),
    key=st.text(min_size=1, max_size=30),
    content=st.binary(min_size=0, max_size=200),
)
@pytest.mark.asyncio
async def test_property_13_store_roundtrip_save_get(
    impl_cls: type[ObjectStore], key: str, content: bytes
) -> None:
    """Round-trip save→get returns the same content, for any conforming implementation."""
    store: ObjectStore = impl_cls()
    reference = await store.save(key, content)
    retrieved = await store.get(reference)
    assert retrieved == content


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(OBJECT_STORE_IMPLEMENTATIONS),
    key=st.text(min_size=1, max_size=30),
    content=st.binary(min_size=0, max_size=200),
)
@pytest.mark.asyncio
async def test_property_13_store_delete_leaves_unavailable(
    impl_cls: type[ObjectStore], key: str, content: bytes
) -> None:
    """delete leaves the object unavailable, for any conforming implementation."""
    store: ObjectStore = impl_cls()
    reference = await store.save(key, content)
    await store.delete(reference)

    with pytest.raises((KeyError, ValueError, IndexError)):
        await store.get(reference)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(QUEUE_IMPLEMENTATIONS),
    topic=st.text(min_size=1, max_size=20),
    message=st.dictionaries(st.text(min_size=1, max_size=10), st.integers(), max_size=5),
)
@pytest.mark.asyncio
async def test_property_13_queue_published_message_is_delivered_to_subscriber(
    impl_cls: type[JobQueue], topic: str, message: dict[str, Any]
) -> None:
    """A message published on a topic is delivered to that topic's subscriber, for any conforming implementation."""
    queue: JobQueue = impl_cls()
    received: list[dict[str, Any]] = []

    async def handler(msg: dict[str, Any]) -> None:
        received.append(msg)

    await queue.subscribe(topic, handler)
    await queue.publish(topic, message)

    assert message in received
