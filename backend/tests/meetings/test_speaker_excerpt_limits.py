"""Behavioral RED tests for bounded speaker-excerpt reads and decoder lifecycle.

All media, storage responses, clocks, and process behavior are synthetic. The
small async service seam is specified here for T-19; no production adapter is
mocked outside these tests.
"""

from __future__ import annotations

import asyncio
import inspect
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.infra.object_store_s3 import S3ObjectStore
from app.meetings import speaker_excerpt_service
from app.meetings.speaker_excerpt_service import ExcerptKeyring, SpeakerExcerptService

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_DURATION_MS = 30_000
MAX_EXCERPT_DURATION_MS = 10_000
OPERATION_BUDGET_SECONDS = 60


@dataclass(frozen=True)
class Candidate:
    start_ms: int
    end_ms: int
    vad_positive_windows: int = 1
    vad_window_count: int = 1
    assigned_speaker_id: str = "speaker-1"


@pytest.fixture
def keyring() -> ExcerptKeyring:
    return ExcerptKeyring(active_key_id="test", keys={"test": b"k" * 32})


def service(
    *,
    decode_interval: Callable[..., Any] | None = None,
    read_interval: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> SpeakerExcerptService:
    keyring = kwargs.pop(
        "keyring", ExcerptKeyring(active_key_id="test", keys={"test": b"k" * 32})
    )
    return SpeakerExcerptService(
        decode_interval=decode_interval or (lambda *_args: b"synthetic-audio"),
        read_interval=read_interval or (lambda *_args: b"synthetic-audio"),
        keyring=keyring,
        **kwargs,
    )


async def derive(
    excerpt_service: SpeakerExcerptService,
    *,
    duration_ms: int | None,
    candidates: list[Candidate],
) -> Any:
    result = excerpt_service.derive(
        recording_id="recording-1",
        revision_id=1,
        speaker_id="speaker-1",
        object_key="synthetic/object",
        audio_duration_ms=duration_ms,
        candidates=candidates,
    )
    return await result if inspect.isawaitable(result) else result


async def play(
    excerpt_service: SpeakerExcerptService,
    *,
    recording_id: str,
    revision_id: int,
    review_item: Any,
) -> bytes:
    result = excerpt_service.play(
        recording_id=recording_id,
        revision_id=revision_id,
        review_item=review_item,
    )
    return await result if inspect.isawaitable(result) else result


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


class RecordingBoundedStore:
    def __init__(self, content: bytes = b"synthetic-source") -> None:
        self.content = content
        self.calls: list[tuple[str, int, float]] = []

    async def get_bounded(
        self, reference: str, max_bytes: int, deadline_monotonic: float
    ) -> bytes:
        self.calls.append((reference, max_bytes, deadline_monotonic))
        return self.content


class CompletedDecoderProcess:
    pid = 919

    def __init__(self) -> None:
        self.returncode: int | None = None

    async def communicate(self, *, input: bytes) -> tuple[bytes, bytes]:
        assert input == b"synthetic-source"
        self.returncode = 0
        return b"managed-synthetic-excerpt", b""

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_service_routes_derive_and_play_through_bounded_store_and_managed_decoder(
    keyring: ExcerptKeyring,
) -> None:
    storage = RecordingBoundedStore()
    spawn_calls: list[tuple[str, ...]] = []
    process = CompletedDecoderProcess()

    async def spawn(*command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        spawn_calls.append(command)
        return process

    decoder = speaker_excerpt_service.ManagedDecoderProcess(spawn_process=spawn)
    excerpt_service = service(
        decode_interval=lambda *_args: b"decoded-by-direct-callback",
        read_interval=lambda *_args: b"read-by-direct-callback",
        keyring=keyring,
    )
    excerpt_service._object_store = storage
    excerpt_service._decoder = decoder
    excerpt = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(100, 1_100)],
    )
    review = SimpleNamespace(meeting_id="recording-1", processing_revision=1)
    item = SimpleNamespace(review=review, speaker_key="speaker-1", excerpt_ref=excerpt.reference)

    result = await play(
        excerpt_service,
        recording_id="recording-1",
        revision_id=1,
        review_item=item,
    )

    assert [call[:2] for call in storage.calls] == [
        ("synthetic/object", MAX_SOURCE_BYTES),
        ("synthetic/object", MAX_SOURCE_BYTES),
    ], "both derive and playback must use the bounded source-read contract"
    assert spawn_calls == [("synthetic-decoder",), ("synthetic-decoder",)]
    assert result == b"managed-synthetic-excerpt"


@pytest.mark.asyncio
async def test_play_rejects_source_over_limit_before_managed_decode(
    keyring: ExcerptKeyring,
) -> None:
    storage = RecordingBoundedStore()
    process = CompletedDecoderProcess()

    async def spawn(*_command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        return process

    excerpt_service = service(
        decode_interval=lambda *_args: b"direct-decode",
        read_interval=lambda *_args: b"direct-playback",
        keyring=keyring,
    )
    excerpt_service._object_store = storage
    excerpt_service._decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn
    )
    excerpt = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(100, 1_100)],
    )
    storage.content = b"x" * (MAX_SOURCE_BYTES + 1)
    review = SimpleNamespace(meeting_id="recording-1", processing_revision=1)
    item = SimpleNamespace(review=review, speaker_key="speaker-1", excerpt_ref=excerpt.reference)

    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await play(
            excerpt_service,
            recording_id="recording-1",
            revision_id=1,
            review_item=item,
        )


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


@pytest.mark.asyncio
async def test_valid_exact_audio_and_excerpt_limits_are_accepted(keyring: ExcerptKeyring) -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> bytes:
        decode_calls.append(args)
        return b"synthetic-audio"

    excerpt_service = service(decode_interval=decode, keyring=keyring)
    result = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS)],
    )

    assert (result.start_ms, result.end_ms) == (0, MAX_EXCERPT_DURATION_MS)
    assert result.reference
    assert decode_calls == [("synthetic/object", 0, MAX_EXCERPT_DURATION_MS)]


@pytest.mark.parametrize("duration_ms", [None, 0, -1, MAX_AUDIO_DURATION_MS + 1])
@pytest.mark.asyncio
async def test_unknown_invalid_or_overlong_audio_is_rejected_before_interval_decode(
    duration_ms: int | None,
) -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> bytes:
        decode_calls.append(args)
        return b"synthetic-audio"

    excerpt_service = service(decode_interval=decode)
    with pytest.raises(Exception) as error:
        await derive(
            excerpt_service,
            duration_ms=duration_ms,
            candidates=[Candidate(0, 5_000)],
        )

    assert not isinstance(error.value, TypeError), "invalid duration must be explicitly rejected"
    assert decode_calls == []


@pytest.mark.asyncio
async def test_overlong_candidate_is_skipped_not_truncated(keyring: ExcerptKeyring) -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> bytes:
        decode_calls.append(args)
        return b"synthetic-audio"

    excerpt_service = service(decode_interval=decode, keyring=keyring)
    result = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS + 1), Candidate(12_000, 22_000)],
    )

    assert (result.start_ms, result.end_ms) == (12_000, 22_000)
    assert decode_calls == [("synthetic/object", 12_000, 22_000)]


@pytest.mark.asyncio
async def test_no_valid_candidate_returns_no_reference_or_partial_decode() -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> bytes:
        decode_calls.append(args)
        return b"synthetic-partial-output"

    excerpt_service = service(decode_interval=decode)
    with pytest.raises(ValueError):
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS + 1)],
        )

    assert decode_calls == []


@pytest.mark.asyncio
async def test_playback_is_awaited_and_returns_only_complete_persisted_excerpt(
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.play)
    read_calls: list[tuple[Any, ...]] = []

    def read(*args: Any, **_kwargs: Any) -> bytes:
        read_calls.append(args)
        return b"complete-synthetic-excerpt"

    excerpt_service = service(read_interval=read, keyring=keyring)
    excerpt = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(100, 1_100)],
    )
    review = SimpleNamespace(meeting_id="recording-1", processing_revision=1)
    item = SimpleNamespace(review=review, speaker_key="speaker-1", excerpt_ref=excerpt.reference)

    result = await play(
        excerpt_service,
        recording_id="recording-1",
        revision_id=1,
        review_item=item,
    )

    assert result == b"complete-synthetic-excerpt"
    assert read_calls == [("synthetic/object", 100, 1_100)]


@pytest.mark.asyncio
async def test_unhealthy_service_rejects_even_when_no_operation_is_active() -> None:
    decode_calls: list[tuple[Any, ...]] = []
    excerpt_service = service(decode_interval=lambda *args: decode_calls.append(args))
    excerpt_service._unhealthy = True

    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )

    assert decode_calls == []


@pytest.mark.asyncio
async def test_sync_decoder_does_not_block_loop_or_release_permit_before_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.01, raising=False)
    worker_started = threading.Event()
    finish_worker = threading.Event()
    threading.Timer(0.2, finish_worker.set).start()

    def blocking_decode(*_args: Any, **_kwargs: Any) -> bytes:
        worker_started.set()
        finish_worker.wait()
        return b"late-synthetic-output"

    excerpt_service = service(decode_interval=blocking_decode)
    operation = asyncio.create_task(
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )
    )
    loop = asyncio.get_running_loop()
    probe_started = loop.time()
    loop_responsive = asyncio.create_task(asyncio.sleep(0.03))
    loop_was_delayed = False
    try:
        await asyncio.wait_for(loop_responsive, timeout=0.08)
    except TimeoutError:
        loop_was_delayed = True
    if not loop_was_delayed:
        with pytest.raises((RuntimeError, ValueError, TimeoutError)):
            await derive(
                excerpt_service,
                duration_ms=MAX_AUDIO_DURATION_MS,
                candidates=[Candidate(1_000, 2_000)],
            )
    finish_worker.set()
    with pytest.raises((RuntimeError, ValueError, TimeoutError)):
        await operation

    assert not loop_was_delayed and loop.time() - probe_started < 0.1, (
        "a synchronous decoder callback must not block the asyncio loop past its budget"
    )


@pytest.mark.asyncio
async def test_one_nonblocking_two_permit_limit_is_shared_by_derive_and_play(
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    assert inspect.iscoroutinefunction(SpeakerExcerptService.play)
    entered: asyncio.Queue[str] = asyncio.Queue()
    release = asyncio.Event()

    async def blocking_decode(*_args: Any, **_kwargs: Any) -> bytes:
        entered.put_nowait("derive")
        await release.wait()
        return b"synthetic-audio"

    async def blocking_read(*_args: Any, **_kwargs: Any) -> bytes:
        entered.put_nowait("play")
        await release.wait()
        return b"synthetic-audio"

    excerpt_service = service(
        decode_interval=blocking_decode,
        read_interval=blocking_read,
        keyring=keyring,
    )
    excerpt = await derive(
        service(keyring=keyring),
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, 1_000)],
    )
    review = SimpleNamespace(meeting_id="recording-1", processing_revision=1)
    item = SimpleNamespace(review=review, speaker_key="speaker-1", excerpt_ref=excerpt.reference)

    first = asyncio.create_task(
        derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)])
    )
    second = asyncio.create_task(
        play(excerpt_service, recording_id="recording-1", revision_id=1, review_item=item)
    )
    assert {await asyncio.wait_for(entered.get(), timeout=0.2) for _ in range(2)} == {"derive", "play"}

    third_started = asyncio.get_running_loop().time()
    with pytest.raises((RuntimeError, ValueError, TimeoutError)):
        await asyncio.wait_for(
            derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)]),
            timeout=0.05,
        )
    assert asyncio.get_running_loop().time() - third_started < 0.05

    release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_one_deadline_is_shared_across_candidate_retries_and_result(
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    deadlines: list[float] = []
    clock = SimpleNamespace(now=100.0)

    async def decode(
        _object_key: str,
        start_ms: int,
        _end_ms: int,
        *,
        deadline_monotonic: float,
    ) -> bytes:
        deadlines.append(deadline_monotonic)
        clock.now += 15.0
        if start_ms == 0:
            raise ValueError("synthetic candidate rejected")
        return b"synthetic-audio"

    excerpt_service = service(decode_interval=decode, monotonic=lambda: clock.now, keyring=keyring)
    await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, 1_000), Candidate(2_000, 3_000)],
    )

    assert deadlines == [
        100.0 + OPERATION_BUDGET_SECONDS,
        100.0 + OPERATION_BUDGET_SECONDS,
    ]


@pytest.mark.asyncio
async def test_timeout_cancels_decoder_and_waits_for_kill_discard_and_reap_before_return(
    monkeypatch: pytest.MonkeyPatch,
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.01, raising=False)
    events: list[str] = []
    never_finish = asyncio.Event()
    active_body = SyntheticBody(len(b"synthetic-source"))

    async def decoder(*_args: Any, **_kwargs: Any) -> bytes:
        events.append("decode_started")
        try:
            await never_finish.wait()
        except asyncio.CancelledError:
            active_body.close()
            events.append("close_active_read")
            events.append("kill_process_group")
            events.append("discard_staged_output")
            await asyncio.sleep(0)
            events.append("reap_process")
            raise
        return b"synthetic-partial-output"

    excerpt_service = service(decode_interval=decoder, keyring=keyring)
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )

    assert events == [
        "decode_started",
        "close_active_read",
        "kill_process_group",
        "discard_staged_output",
        "reap_process",
    ]
    assert active_body.closed


@pytest.mark.asyncio
async def test_unconfirmed_exit_holds_operation_and_rejects_new_work_until_reaped(
    monkeypatch: pytest.MonkeyPatch,
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.01, raising=False)
    reap_confirmed = asyncio.Event()
    process_events: list[str] = []

    async def unconfirmed_decoder(*_args: Any, **_kwargs: Any) -> bytes:
        process_events.append("decode_started")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            process_events.extend(("kill_process_group", "discard_staged_output", "reap_pending"))
            await reap_confirmed.wait()
            process_events.append("reap_confirmed")
            raise
        raise AssertionError("synthetic decoder unexpectedly completed")

    excerpt_service = service(decode_interval=unconfirmed_decoder, keyring=keyring)
    operation = asyncio.create_task(
        derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)])
    )
    await asyncio.sleep(0.03)

    assert not operation.done(), "the service must not release a permit while process exit is unconfirmed"
    assert process_events == [
        "decode_started",
        "kill_process_group",
        "discard_staged_output",
        "reap_pending",
    ]
    with pytest.raises((RuntimeError, ValueError, TimeoutError)):
        await asyncio.wait_for(
            derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)]),
            timeout=0.05,
        )

    reap_confirmed.set()
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await operation
    assert process_events[-1] == "reap_confirmed"


@pytest.mark.asyncio
async def test_decoder_failure_is_generic_at_service_boundary(keyring: ExcerptKeyring) -> None:
    def decoder_failure(*_args: Any, **_kwargs: Any) -> bytes:
        raise ValueError("secret-storage-endpoint decoder argv=/private/path")

    excerpt_service = service(decode_interval=decoder_failure, keyring=keyring)

    with pytest.raises(ValueError) as error:
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )

    message = str(error.value).lower()
    assert message
    for internal_fragment in (
        "secret-storage-endpoint",
        "decoder argv",
        "/private/path",
        "synthetic/object",
    ):
        assert internal_fragment not in message


class SyntheticChildProcess:
    """External child-process adapter whose exit is controlled by each test."""

    pid = 731

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.exited = asyncio.Event()

    async def communicate(self, **kwargs: Any) -> tuple[bytes, bytes]:
        assert kwargs["input"] == b"synthetic-source"
        self.events.append("communicate_started")
        await self.exited.wait()
        self.events.append("communicate_finished")
        return b"synthetic-partial-output", b"private-decoder-diagnostic"

    async def wait(self) -> int:
        self.events.append("wait_started")
        await self.exited.wait()
        self.events.append("wait_confirmed")
        return -signal.SIGKILL


# T-19 seam: the production managed decoder accepts a synthetic process spawner
# and kill-group adapter so tests exercise its lifecycle orchestration without OS media.
def managed_decoder_for_test(
    events: list[str], *, confirm_exit_on_kill: bool
) -> tuple[Any, SyntheticChildProcess]:
    decoder_type = getattr(speaker_excerpt_service, "ManagedDecoderProcess", None)
    assert callable(decoder_type), (
        "T-19 must provide ManagedDecoderProcess to supervise process-group kill and reap"
    )
    process = SyntheticChildProcess(events)

    async def spawn_process(*command: str, start_new_session: bool) -> SyntheticChildProcess:
        assert command == ("synthetic-decoder",)
        assert start_new_session, "decoder must run in its own killable process group"
        events.append("spawned_process_group")
        return process

    def kill_process_group(pid: int, sig: signal.Signals) -> None:
        assert pid == process.pid
        assert sig == signal.SIGKILL, "timeout must hard-kill the decoder process group"
        events.append("killed_process_group")
        if confirm_exit_on_kill:
            process.exited.set()

    decoder = decoder_type(
        spawn_process=spawn_process,
        kill_process_group=kill_process_group,
        monotonic=lambda: 0.0,
    )
    return decoder, process


@pytest.mark.asyncio
async def test_managed_decoder_spawn_is_bounded_by_deadline() -> None:
    spawn_started = asyncio.Event()
    spawn_cancelled = asyncio.Event()
    release_spawn = asyncio.Event()

    async def blocked_spawn(*_command: str, start_new_session: bool) -> Any:
        assert start_new_session
        spawn_started.set()
        try:
            await release_spawn.wait()
        except asyncio.CancelledError:
            spawn_cancelled.set()
            raise
        raise AssertionError("spawn should have timed out before release")

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=blocked_spawn,
        monotonic=lambda: 0.0,
    )
    operation = asyncio.create_task(
        decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.01,
        )
    )
    await spawn_started.wait()
    await asyncio.sleep(0.03)
    spawn_timed_out = operation.done()
    if not spawn_timed_out:
        operation.cancel()
    with pytest.raises((TimeoutError, ValueError, RuntimeError, asyncio.CancelledError)):
        await operation

    assert spawn_timed_out, "decoder process creation must honor the remaining operation budget"
    assert spawn_cancelled.is_set()


@pytest.mark.asyncio
async def test_managed_decoder_hard_kills_and_reaps_before_discarding_timed_out_output() -> None:
    events: list[str] = []
    decoder, _process = managed_decoder_for_test(events, confirm_exit_on_kill=True)

    with pytest.raises((TimeoutError, ValueError, RuntimeError)) as error:
        await decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.01,
        )

    assert events[:2] == ["spawned_process_group", "communicate_started"]
    assert events.index("killed_process_group") < events.index("wait_started")
    assert events.index("wait_started") < events.index("wait_confirmed")
    assert "synthetic-partial-output" not in str(error.value)
    assert "private-decoder-diagnostic" not in str(error.value)


@pytest.mark.asyncio
async def test_managed_decoder_does_not_return_until_process_exit_is_confirmed() -> None:
    events: list[str] = []
    decoder, process = managed_decoder_for_test(events, confirm_exit_on_kill=False)
    operation = asyncio.create_task(
        decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.01,
        )
    )

    await asyncio.sleep(0.03)
    assert not operation.done(), "an unconfirmed process exit cannot release its caller"
    assert events == [
        "spawned_process_group",
        "communicate_started",
        "killed_process_group",
        "wait_started",
    ]

    process.exited.set()
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await operation
    assert events.index("wait_started") < events.index("wait_confirmed")


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_decoder_reap() -> None:
    events: list[str] = []
    decoder, process = managed_decoder_for_test(events, confirm_exit_on_kill=False)
    operation = asyncio.create_task(
        decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.01,
        )
    )
    await asyncio.sleep(0.03)
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    await asyncio.sleep(0.01)

    assert not operation.done(), "repeated cancellation must not abandon process reaping"
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
    process.exited.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
    assert "wait_confirmed" in events


@pytest.mark.asyncio
async def test_service_holds_permit_until_managed_decoder_exit_is_confirmed(
    keyring: ExcerptKeyring,
) -> None:
    events: list[str] = []
    managed_decoder, process = managed_decoder_for_test(events, confirm_exit_on_kill=False)
    decode_calls: list[int] = []

    async def decode_interval(
        _object_key: str,
        start_ms: int,
        _end_ms: int,
        **_kwargs: Any,
    ) -> bytes:
        decode_calls.append(start_ms)
        if start_ms == 0:
            return cast(
                bytes,
                await managed_decoder.run(
                    ("synthetic-decoder",),
                    input_bytes=b"synthetic-source",
                    deadline_monotonic=0.01,
                ),
            )
        return b"synthetic-complete-output"

    excerpt_service = service(decode_interval=decode_interval, keyring=keyring)
    first_request = asyncio.create_task(
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )
    )
    await asyncio.sleep(0.03)
    assert not first_request.done()
    assert "killed_process_group" in events
    assert "wait_started" in events
    assert "wait_confirmed" not in events

    for start_ms in (1_000, 2_000):
        rejected_request_started = asyncio.get_running_loop().time()
        with pytest.raises((RuntimeError, ValueError, TimeoutError)):
            await asyncio.wait_for(
                derive(
                    excerpt_service,
                    duration_ms=MAX_AUDIO_DURATION_MS,
                    candidates=[Candidate(start_ms, start_ms + 1_000)],
                ),
                timeout=0.1,
            )
        assert asyncio.get_running_loop().time() - rejected_request_started < 0.1
    assert decode_calls == [0], "unhealthy worker rejection must happen before interval decoding"
    assert "wait_confirmed" not in events

    process.exited.set()
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await first_request
    assert "wait_confirmed" in events

    await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(2_000, 3_000)],
    )
