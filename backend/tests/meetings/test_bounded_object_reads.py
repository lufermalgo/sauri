"""Retain bounded object-store regression tests after retiring audio clips."""

from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import Any, cast

import pytest

from app.infra.object_store_s3 import S3ObjectStore

MAX_SOURCE_BYTES = 20 * 1024 * 1024


def bounded_read(
    store: S3ObjectStore, *, max_bytes: int, deadline_monotonic: float
) -> Awaitable[bytes]:
    method = getattr(store, "get_bounded", None)
    assert callable(method), (
        "the bounded-read behavior requires get_bounded(reference, max_bytes, deadline_monotonic)"
    )
    return cast(
        Awaitable[bytes],
        method(
            "synthetic/object",
            max_bytes=max_bytes,
            deadline_monotonic=deadline_monotonic,
        ),
    )


class SyntheticBody:
    def __init__(self, content_size: int, *, fail_after: int | None = None) -> None:
        self.content_size = content_size
        self.offset = 0
        self.read_sizes: list[int] = []
        self.returned_bytes = 0
        self.closed = False
        self.fail_after = fail_after

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.fail_after is not None and self.offset >= self.fail_after:
            raise OSError("synthetic body read failed")
        stop = self.content_size if size < 0 else min(self.offset + size, self.content_size)
        chunk_size = stop - self.offset
        self.offset = stop
        self.returned_bytes += chunk_size
        return b"x" * chunk_size

    def close(self) -> None:
        self.closed = True


class SyntheticS3Client:
    def __init__(self, *, length: int | None, body: SyntheticBody) -> None:
        self.length = length
        self.body = body
        self.calls: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        response: dict[str, Any] = {"Body": self.body}
        if self.length is not None:
            response["ContentLength"] = self.length
        return response


@pytest.mark.asyncio
async def test_late_s3_response_body_is_closed_after_deadline(object_store: S3ObjectStore) -> None:
    body = SyntheticBody(1)

    class DelayedClient(SyntheticS3Client):
        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            time.sleep(0.05)
            return super().get_object(**kwargs)

    object_store._client = DelayedClient(length=1, body=body)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await object_store.get_bounded(
            "synthetic/object",
            max_bytes=10,
            deadline_monotonic=started + 0.01,
        )
    assert body.closed, "a response arriving after timeout must be closed before releasing the operation"


@pytest.fixture

def object_store() -> S3ObjectStore:
    store = S3ObjectStore(
        endpoint_url="http://synthetic.invalid",
        bucket="synthetic-bucket",
        access_key="synthetic-access-key",
        secret_key="synthetic-secret-key",
    )
    return store


@pytest.mark.asyncio
async def test_exact_source_limit_reads_one_sentinel_and_closes_body(
    object_store: S3ObjectStore,
) -> None:
    body = SyntheticBody(MAX_SOURCE_BYTES)
    client = SyntheticS3Client(length=MAX_SOURCE_BYTES, body=body)
    object_store._client = client

    result = await bounded_read(
        object_store,
        max_bytes=MAX_SOURCE_BYTES,
        deadline_monotonic=time.monotonic() + 60.0,
    )

    assert len(result) == MAX_SOURCE_BYTES
    assert body.returned_bytes == MAX_SOURCE_BYTES
    assert body.read_sizes[-1] in {1, MAX_SOURCE_BYTES + 1}, (
        "an exact-limit object must be checked with one sentinel byte"
    )
    assert body.returned_bytes <= MAX_SOURCE_BYTES + 1
    assert body.closed
    assert client.calls == [{"Bucket": "synthetic-bucket", "Key": "synthetic/object"}]


@pytest.mark.parametrize(
    ("declared_length", "content_size"),
    [
        (MAX_SOURCE_BYTES + 1, 9),
        (MAX_SOURCE_BYTES, MAX_SOURCE_BYTES + 1),
        (None, 9),
        (9, 8),
        (3, 4),
    ],
)
@pytest.mark.asyncio
async def test_unknown_oversized_or_divergent_source_is_rejected_without_partial_bytes(
    object_store: S3ObjectStore,
    declared_length: int | None,
    content_size: int,
) -> None:
    body = SyntheticBody(content_size)
    object_store._client = SyntheticS3Client(length=declared_length, body=body)

    with pytest.raises((ValueError, OSError)):
        await bounded_read(
            object_store,
            max_bytes=MAX_SOURCE_BYTES,
            deadline_monotonic=time.monotonic() + 60.0,
        )

    assert body.closed
    assert body.returned_bytes <= MAX_SOURCE_BYTES + 1


@pytest.mark.asyncio
async def test_expired_deadline_rejects_before_object_retrieval(object_store: S3ObjectStore) -> None:
    body = SyntheticBody(len(b"synthetic"))
    client = SyntheticS3Client(length=9, body=body)
    object_store._client = client

    with pytest.raises((ValueError, OSError, TimeoutError)):
        await bounded_read(
            object_store,
            max_bytes=MAX_SOURCE_BYTES,
            deadline_monotonic=0.0,
        )

    assert client.calls == []
    assert body.read_sizes == []
    assert not body.closed, "no response body exists before retrieval"


@pytest.mark.asyncio
async def test_body_closes_when_bounded_read_fails(object_store: S3ObjectStore) -> None:
    body = SyntheticBody(len(b"123456"), fail_after=0)
    object_store._client = SyntheticS3Client(length=6, body=body)

    with pytest.raises(OSError):
        await bounded_read(
            object_store,
            max_bytes=10,
            deadline_monotonic=time.monotonic() + 60.0,
        )

    assert body.closed
