"""Behavioral RED tests for bounded speaker-excerpt reads and decoder lifecycle.

All media, storage responses, clocks, and process behavior are synthetic. The
small async service seam is specified here for T-19; no production adapter is
mocked outside these tests.
"""

from __future__ import annotations

import asyncio
import inspect
import signal
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
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
    monotonic = kwargs.pop("monotonic", time.monotonic)
    object_store = kwargs.pop("object_store", RecordingBoundedStore())
    decoder = kwargs.pop("decoder", synthetic_managed_decoder(monotonic=monotonic))
    probe_audio = kwargs.pop("probe_audio", lambda: ("synthetic-probe",))
    service_args = {
        "object_store": object_store,
        "decoder": decoder,
        "decode_interval": decode_interval or (lambda *_args: ("synthetic-decoder",)),
        "read_interval": read_interval or (lambda *_args: ("synthetic-decoder",)),
        "keyring": keyring,
        "monotonic": monotonic,
        **kwargs,
    }
    if "probe_audio" in inspect.signature(SpeakerExcerptService.__init__).parameters:
        return SpeakerExcerptService(**service_args, probe_audio=probe_audio)
    excerpt_service = SpeakerExcerptService(**service_args)
    excerpt_service._probe_audio = probe_audio
    return excerpt_service


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


class SyntheticInput:
    def write(self, _data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class SyntheticOutput:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class CompletedDecoderProcess:
    pid = 919

    def __init__(self, output: bytes = b"managed-synthetic-excerpt") -> None:
        self.returncode: int | None = None
        self.stdin = SyntheticInput()
        self.stdout = SyntheticOutput(output)

    async def communicate(self, **kwargs: Any) -> tuple[bytes, bytes]:
        assert kwargs["input"] == b"synthetic-source"
        return self.stdout.content, b""

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def synthetic_managed_decoder(
    *, monotonic: Callable[[], float] = time.monotonic
) -> speaker_excerpt_service.ManagedDecoderProcess:
    async def spawn(*command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        output = b"30.0" if command == ("synthetic-probe",) else b"managed-synthetic-excerpt"
        return CompletedDecoderProcess(output)

    return speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn,
        kill_process_group=lambda _pid, _signal: None,
        process_group_exists=lambda _pid: False,
        monotonic=monotonic,
    )


@pytest.mark.asyncio
async def test_service_routes_derive_and_play_through_bounded_store_and_managed_decoder(
    keyring: ExcerptKeyring,
) -> None:
    storage = RecordingBoundedStore()
    spawn_calls: list[tuple[str, ...]] = []
    async def spawn(*command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        spawn_calls.append(command)
        output = b"30.0" if command == ("synthetic-probe",) else b"managed-synthetic-excerpt"
        return CompletedDecoderProcess(output)

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn,
        process_group_exists=lambda _pid: False,
    )
    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-decoder",),
        read_interval=lambda *_args: ("synthetic-decoder",),
        object_store=storage,
        decoder=decoder,
        keyring=keyring,
    )
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
    assert spawn_calls == [
        ("synthetic-probe",),
        ("synthetic-decoder",),
        ("synthetic-probe",),
        ("synthetic-decoder",),
    ]
    assert result == b"managed-synthetic-excerpt"


@pytest.mark.asyncio
async def test_play_rejects_source_over_limit_before_managed_decode(
    keyring: ExcerptKeyring,
) -> None:
    storage = RecordingBoundedStore()
    spawn_calls: list[tuple[str, ...]] = []

    async def spawn(*command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        spawn_calls.append(command)
        output = b"30.0" if command == ("synthetic-probe",) else b"managed-synthetic-excerpt"
        return CompletedDecoderProcess(output)

    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-decoder",),
        read_interval=lambda *_args: ("synthetic-decoder",),
        object_store=storage,
        decoder=speaker_excerpt_service.ManagedDecoderProcess(
            spawn_process=spawn,
            process_group_exists=lambda _pid: False,
        ),
        keyring=keyring,
    )
    excerpt = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(100, 1_100)],
    )
    spawn_calls.clear()
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
    assert spawn_calls == [], "oversized source bytes must be rejected before child creation"


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

    def decode(*args: Any, **_kwargs: Any) -> tuple[str, ...]:
        decode_calls.append(args)
        return ("synthetic-decoder",)

    excerpt_service = service(decode_interval=decode, keyring=keyring)
    result = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS)],
    )

    assert (result.start_ms, result.end_ms) == (0, MAX_EXCERPT_DURATION_MS)
    assert result.reference
    assert decode_calls == [(0, MAX_EXCERPT_DURATION_MS)]


@pytest.mark.asyncio
async def test_derive_rejects_unverified_or_overlong_source_duration_before_interval_decode(
    keyring: ExcerptKeyring,
) -> None:
    decode_calls: list[tuple[int, int]] = []
    probe_outputs = iter((b"not-audio", b"30.001", b"5.0"))

    async def spawn(*command: str, start_new_session: bool) -> CompletedDecoderProcess:
        assert start_new_session
        output = next(probe_outputs) if command == ("synthetic-probe",) else b"managed-synthetic-excerpt"
        return CompletedDecoderProcess(output)

    def decode_interval(start_ms: int, end_ms: int) -> tuple[str, ...]:
        decode_calls.append((start_ms, end_ms))
        return ("synthetic-decoder",)

    def legacy_compatible_decode(*args: Any) -> tuple[str, ...]:
        start, end = args[-2:]
        return decode_interval(start, end)

    excerpt_service = service(
        decoder=speaker_excerpt_service.ManagedDecoderProcess(
            spawn_process=spawn,
            process_group_exists=lambda _pid: False,
        ),
        decode_interval=legacy_compatible_decode,
        probe_audio=lambda: ("synthetic-probe",),
        keyring=keyring,
    )
    for _ in range(2):
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await derive(
                excerpt_service,
                duration_ms=MAX_AUDIO_DURATION_MS,
                candidates=[Candidate(0, 1_000)],
            )
    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 6_000)],
        )

    assert decode_calls == []


@pytest.mark.parametrize("duration_ms", [None, 0, -1, MAX_AUDIO_DURATION_MS + 1])
@pytest.mark.asyncio
async def test_unknown_invalid_or_overlong_audio_is_rejected_before_interval_decode(
    duration_ms: int | None,
) -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> tuple[str, ...]:
        decode_calls.append(args)
        return ("synthetic-decoder",)

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

    def decode(*args: Any, **_kwargs: Any) -> tuple[str, ...]:
        decode_calls.append(args)
        return ("synthetic-decoder",)

    excerpt_service = service(decode_interval=decode, keyring=keyring)
    result = await derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS + 1), Candidate(12_000, 22_000)],
    )

    assert (result.start_ms, result.end_ms) == (12_000, 22_000)
    assert decode_calls == [(12_000, 22_000)]


@pytest.mark.asyncio
async def test_no_valid_candidate_returns_no_reference_or_partial_decode() -> None:
    decode_calls: list[tuple[Any, ...]] = []

    def decode(*args: Any, **_kwargs: Any) -> tuple[str, ...]:
        decode_calls.append(args)
        return ("synthetic-decoder",)

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

    def read(*args: Any, **_kwargs: Any) -> tuple[str, ...]:
        read_calls.append(args)
        return ("synthetic-decoder",)

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

    assert result == b"managed-synthetic-excerpt"
    assert read_calls == [(100, 1_100)]


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
async def test_decoder_work_runs_in_child_without_blocking_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 1.0, raising=False)
    decoder_started = asyncio.Event()
    release_decoder = asyncio.Event()

    class BlockingOutput:
        def __init__(self) -> None:
            self.finished = False

        async def read(self, _size: int) -> bytes:
            if self.finished:
                return b""
            await release_decoder.wait()
            self.finished = True
            return b"synthetic-excerpt"

    class BlockingProcess:
        pid = 772
        returncode: int | None = None

        def __init__(self) -> None:
            self.stdin = SyntheticInput()
            self.stdout = BlockingOutput()

        async def wait(self) -> int:
            self.returncode = 0
            return 0

    async def spawn(*command: str, start_new_session: bool) -> Any:
        assert start_new_session
        if command == ("synthetic-probe",):
            return CompletedDecoderProcess(b"30.0")
        decoder_started.set()
        return BlockingProcess()

    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-decoder",),
        decoder=speaker_excerpt_service.ManagedDecoderProcess(
            spawn_process=spawn,
            process_group_exists=lambda _pid: False,
        ),
    )
    operation = asyncio.create_task(
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )
    )
    await decoder_started.wait()
    await asyncio.wait_for(asyncio.sleep(0.03), timeout=0.08)
    release_decoder.set()
    result = await operation

    assert (result.start_ms, result.end_ms) == (0, 1_000)


@pytest.mark.asyncio
async def test_one_nonblocking_two_permit_limit_is_shared_by_derive_and_play(
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    assert inspect.iscoroutinefunction(SpeakerExcerptService.play)
    entered: asyncio.Queue[str] = asyncio.Queue()
    release = asyncio.Event()

    class BlockingOutput:
        def __init__(self, label: str, result: bytes) -> None:
            self.label = label
            self.result = result
            self.finished = False

        async def read(self, _size: int) -> bytes:
            if self.finished:
                return b""
            entered.put_nowait(self.label)
            await release.wait()
            self.finished = True
            return self.result

    class BlockingProcess:
        pid = 731
        returncode: int | None = None

        def __init__(self, label: str, result: bytes) -> None:
            self.stdin = SyntheticInput()
            self.stdout = BlockingOutput(label, result)

        async def wait(self) -> int:
            self.returncode = 0
            return 0

    async def spawn(*command: str, start_new_session: bool) -> Any:
        assert start_new_session
        if command == ("synthetic-probe",):
            return CompletedDecoderProcess(b"30.0")
        return BlockingProcess(command[1], b"managed-synthetic-excerpt")

    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-blocking", "derive"),
        read_interval=lambda *_args: ("synthetic-blocking", "play"),
        decoder=speaker_excerpt_service.ManagedDecoderProcess(
            spawn_process=spawn,
            process_group_exists=lambda _pid: False,
        ),
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
async def test_one_deadline_is_shared_across_probe_candidates_and_result(
    keyring: ExcerptKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    deadlines: list[float] = []
    clock = SimpleNamespace(now=100.0)
    decoder = synthetic_managed_decoder(monotonic=lambda: clock.now)
    original_run = decoder.run

    async def recording_run(
        command: tuple[str, ...],
        *,
        input_bytes: bytes,
        deadline_monotonic: float,
        max_output_bytes: int = speaker_excerpt_service.MAX_DECODER_OUTPUT_BYTES,
        on_reap: Callable[[asyncio.Task[bool]], None] | None = None,
    ) -> bytes:
        if command != ("synthetic-probe",):
            deadlines.append(deadline_monotonic)
            clock.now += 15.0
            if command[2] == "0":
                raise ValueError("synthetic candidate rejected")
        return await original_run(
            command,
            input_bytes=input_bytes,
            deadline_monotonic=deadline_monotonic,
            max_output_bytes=max_output_bytes,
            on_reap=on_reap,
        )

    monkeypatch.setattr(decoder, "run", recording_run)
    excerpt_service = service(
        decode_interval=lambda start_ms, end_ms: (
            "synthetic-decoder",
            "interval",
            str(start_ms),
            str(end_ms),
        ),
        decoder=decoder,
        monotonic=lambda: clock.now,
        keyring=keyring,
    )
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
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.2, raising=False)
    events: list[str] = []
    managed_decoder, _process = managed_decoder_for_test(
        events, confirm_exit_on_kill=True, monotonic=time.monotonic
    )
    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-decoder",),
        decoder=managed_decoder,
        keyring=keyring,
    )
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )

    assert events == [
        "spawned_process_group",
        "communicate_started",
        "killed_process_group",
        "communicate_finished",
        "wait_started",
        "wait_confirmed",
    ]


@pytest.mark.asyncio
async def test_unconfirmed_exit_holds_operation_and_rejects_new_work_until_reaped(
    monkeypatch: pytest.MonkeyPatch,
    keyring: ExcerptKeyring,
) -> None:
    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.2, raising=False)
    process_events: list[str] = []
    managed_decoder, process = managed_decoder_for_test(
        process_events, confirm_exit_on_kill=False, monotonic=time.monotonic
    )
    excerpt_service = service(
        decode_interval=lambda *_args: ("synthetic-decoder",),
        decoder=managed_decoder,
        keyring=keyring,
    )
    operation = asyncio.create_task(
        derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)])
    )
    await asyncio.sleep(0.25)

    assert operation.done(), "deadline response should return while the background reaper retains the permit"
    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await operation
    assert process_events == [
        "spawned_process_group",
        "communicate_started",
        "killed_process_group",
    ]
    assert "wait_started" not in process_events
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 1
    with pytest.raises((RuntimeError, ValueError, TimeoutError)):
        await asyncio.wait_for(
            derive(excerpt_service, duration_ms=MAX_AUDIO_DURATION_MS, candidates=[Candidate(0, 1_000)]),
            timeout=0.05,
        )

    process.exited.set()
    for _ in range(10):
        if (
            speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
            and speaker_excerpt_service._PROCESS_PERMITS._value == 2
        ):
            break
        await asyncio.sleep(0)
    assert process_events[-3:] == [
        "communicate_finished",
        "wait_started",
        "wait_confirmed",
    ]
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 2


@pytest.mark.asyncio
async def test_decoder_rejects_stdout_over_explicit_output_cap() -> None:
    class OversizedOutputProcess(CompletedDecoderProcess):
        def __init__(self) -> None:
            super().__init__(b"x" * (20 * 1024 * 1024 + 1))

    spawned: list[OversizedOutputProcess] = []

    async def spawn(*_command: str, start_new_session: bool) -> OversizedOutputProcess:
        assert start_new_session
        process = OversizedOutputProcess()
        spawned.append(process)
        return process

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn,
        process_group_exists=lambda _pid: False,
    )
    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=time.monotonic() + 5,
        )
    assert spawned[0].stdout.offset == 20 * 1024 * 1024 + 1


@pytest.mark.asyncio
async def test_timed_out_request_returns_while_reaper_retains_permit_and_rejects_work(
    keyring: ExcerptKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.2, raising=False)
    events: list[str] = []
    managed_decoder, process = managed_decoder_for_test(
        events, confirm_exit_on_kill=False, monotonic=time.monotonic
    )
    excerpt_service = service(decoder=managed_decoder, keyring=keyring)
    request = asyncio.create_task(
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )
    )
    try:
        for _ in range(100):
            if "communicate_started" in events:
                break
            await asyncio.sleep(0.005)
        assert "communicate_started" in events
        done, _pending = await asyncio.wait({request}, timeout=0.3)
        assert request in done, "deadline response must not wait for the background reaper"
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await request
        assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
        assert speaker_excerpt_service._PROCESS_PERMITS._value == 1
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await derive(
                excerpt_service,
                duration_ms=MAX_AUDIO_DURATION_MS,
                candidates=[Candidate(0, 1_000)],
            )
    finally:
        process.exited.set()
        if not request.done():
            await asyncio.wait({request}, timeout=0.2)
        if request.done() and not request.cancelled():
            with suppress(ValueError):
                request.exception()
        for _ in range(100):
            if (
                speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
                and speaker_excerpt_service._PROCESS_PERMITS._value == 2
            ):
                break
            await asyncio.sleep(0.005)
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 2


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
        self.returncode: int | None = None
        self.stdin = SyntheticInput()
        self.stdout = self
        self._output_read = False

    async def read(self, _size: int) -> bytes:
        if self._output_read:
            return b""
        self.events.append("communicate_started")
        await self.exited.wait()
        self.events.append("communicate_finished")
        self._output_read = True
        return b"synthetic-partial-output"

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
        self.returncode = -signal.SIGKILL
        return -signal.SIGKILL


# T-19 seam: the production managed decoder accepts a synthetic process spawner
# and kill-group adapter so tests exercise its lifecycle orchestration without OS media.
def managed_decoder_for_test(
    events: list[str],
    *,
    confirm_exit_on_kill: bool,
    process_group_exists: Callable[[int], bool | None] | None = None,
    monotonic: Callable[[], float] = lambda: 0.0,
) -> tuple[Any, SyntheticChildProcess]:
    decoder_type = getattr(speaker_excerpt_service, "ManagedDecoderProcess", None)
    assert callable(decoder_type), (
        "T-19 must provide ManagedDecoderProcess to supervise process-group kill and reap"
    )
    process = SyntheticChildProcess(events)

    async def spawn_process(*command: str, start_new_session: bool) -> Any:
        assert start_new_session, "decoder must run in its own killable process group"
        if command == ("synthetic-probe",):
            return CompletedDecoderProcess(b"30.0")
        assert command == ("synthetic-decoder",)
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
        process_group_exists=process_group_exists
        or (lambda pid: pid == process.pid and not process.exited.is_set()),
        monotonic=monotonic,
    )
    return decoder, process


@pytest.mark.asyncio
async def test_managed_decoder_confirms_process_group_exit_after_success() -> None:
    checked_groups: list[int] = []

    async def spawn_process(*_command: str, start_new_session: bool) -> Any:
        assert start_new_session
        return CompletedDecoderProcess(b"synthetic-success")

    def process_group_exists(process_group_id: int) -> bool:
        checked_groups.append(process_group_id)
        return False

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn_process,
        process_group_exists=process_group_exists,
        monotonic=lambda: 0.0,
    )

    result = await decoder.run(
        ("synthetic-decoder",),
        input_bytes=b"synthetic-source",
        deadline_monotonic=1.0,
    )

    assert result == b"synthetic-success"
    assert checked_groups == [CompletedDecoderProcess.pid], (
        "successful output must not return until process-group exit is confirmed"
    )


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
async def test_timeout_reaps_descendant_held_stdout_before_releasing_permit() -> None:
    pipe_closed = asyncio.Event()
    kill_called = asyncio.Event()
    leader_reaped = asyncio.Event()
    class ExitedLeaderWithInheritedStdout:
        pid = 842
        returncode: int | None = 0
        stdin = SyntheticInput()
        stdout = None

        def __init__(self) -> None:
            self.stdout = self
            self.output_finished = False

        async def read(self, _size: int) -> bytes:
            await pipe_closed.wait()
            if self.output_finished:
                return b""
            self.output_finished = True
            return b""

        async def communicate(self, **kwargs: Any) -> tuple[bytes, bytes]:
            assert kwargs["input"] == b"synthetic-source"
            await pipe_closed.wait()
            return b"", b""

        async def wait(self) -> int:
            leader_reaped.set()
            return 0

    process = ExitedLeaderWithInheritedStdout()

    async def spawn_process(*_command: str, start_new_session: bool) -> Any:
        return process

    def kill_process_group(pid: int, sig: signal.Signals) -> None:
        assert pid == process.pid
        assert sig == signal.SIGKILL
        kill_called.set()

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn_process,
        kill_process_group=kill_process_group,
    )
    await speaker_excerpt_service._PROCESS_PERMITS.acquire()
    lease = speaker_excerpt_service._OperationLease(time.monotonic() + 0.05)
    try:
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await decoder.run(
                ("synthetic-decoder",),
                input_bytes=b"synthetic-source",
                deadline_monotonic=lease.deadline_monotonic,
                on_reap=lease.defer_release_until,
            )
        lease.release()
        assert kill_called.is_set(), "timeout must kill descendants even after leader exit"
        assert not leader_reaped.is_set(), "reaper must wait for descendant-held stdout to close"
        assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
        assert speaker_excerpt_service._PROCESS_PERMITS._value == 1
    finally:
        pipe_closed.set()
        lease.release()

    for _ in range(100):
        if (
            speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
            and speaker_excerpt_service._PROCESS_PERMITS._value == 2
        ):
            break
        await asyncio.sleep(0.005)
    assert leader_reaped.is_set()
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 2


@pytest.mark.asyncio
async def test_failed_group_kill_keeps_worker_unhealthy_and_permit_after_leader_exit() -> None:
    stdout_eof = asyncio.Event()
    kill_failed = asyncio.Event()
    reapers: list[asyncio.Task[Any]] = []

    class ExitedLeader:
        pid = 943
        returncode: int | None = 0
        stdin = SyntheticInput()
        stdout = None

        def __init__(self) -> None:
            self.stdout = self

        async def read(self, _size: int) -> bytes:
            await stdout_eof.wait()
            return b""

        async def wait(self) -> int:
            return 0

    process = ExitedLeader()

    async def spawn_process(*_command: str, start_new_session: bool) -> Any:
        assert start_new_session
        return process

    def kill_process_group(_pid: int, _sig: signal.Signals) -> None:
        kill_failed.set()
        raise PermissionError("synthetic process-group permission failure")

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn_process,
        kill_process_group=kill_process_group,
    )
    initial_health = speaker_excerpt_service._UNCONFIRMED_DECODERS
    initial_permits = speaker_excerpt_service._PROCESS_PERMITS._value
    await speaker_excerpt_service._PROCESS_PERMITS.acquire()
    lease = speaker_excerpt_service._OperationLease(time.monotonic() + 0.01)

    def record_reaper(task: asyncio.Task[Any]) -> None:
        reapers.append(task)
        lease.defer_release_until(task)

    try:
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await decoder.run(
                ("synthetic-decoder",),
                input_bytes=b"synthetic-source",
                deadline_monotonic=lease.deadline_monotonic,
                on_reap=record_reaper,
            )
        lease.release()
        assert kill_failed.is_set()
        assert len(reapers) == 1

        stdout_eof.set()
        await reapers[0]

        expected_health = initial_health + 1
        expected_permits = initial_permits - 1
        assert expected_health == speaker_excerpt_service._UNCONFIRMED_DECODERS
        assert speaker_excerpt_service._PROCESS_PERMITS._value == expected_permits
    finally:
        stdout_eof.set()
        for reaper in reapers:
            if not reaper.done():
                with suppress(BaseException):
                    await reaper
        speaker_excerpt_service._UNCONFIRMED_DECODERS = initial_health
        if speaker_excerpt_service._PROCESS_PERMITS._value < initial_permits:
            speaker_excerpt_service._PROCESS_PERMITS.release()


@pytest.mark.asyncio
async def test_managed_decoder_retains_permit_until_process_group_disappears() -> None:
    stdout_eof = asyncio.Event()
    group_gone = asyncio.Event()
    probe_called = asyncio.Event()
    reapers: list[asyncio.Task[Any]] = []

    class ExitedLeader:
        pid = 977
        returncode: int | None = 0
        stdin = SyntheticInput()
        stdout = None

        def __init__(self) -> None:
            self.stdout = self

        async def read(self, _size: int) -> bytes:
            await stdout_eof.wait()
            return b""

        async def wait(self) -> int:
            return 0

    process = ExitedLeader()

    async def spawn_process(*_command: str, start_new_session: bool) -> Any:
        assert start_new_session
        return process

    def kill_process_group(pid: int, sig: signal.Signals) -> None:
        assert pid == process.pid
        assert sig == signal.SIGKILL

    def process_group_exists(pid: int) -> bool:
        assert pid == process.pid
        probe_called.set()
        return not group_gone.is_set()

    decoder = speaker_excerpt_service.ManagedDecoderProcess(
        spawn_process=spawn_process,
        kill_process_group=kill_process_group,
        process_group_exists=process_group_exists,
    )
    initial_health = speaker_excerpt_service._UNCONFIRMED_DECODERS
    initial_permits = speaker_excerpt_service._PROCESS_PERMITS._value
    await speaker_excerpt_service._PROCESS_PERMITS.acquire()
    lease = speaker_excerpt_service._OperationLease(time.monotonic() + 0.02)

    def record_reaper(task: asyncio.Task[Any]) -> None:
        reapers.append(task)
        lease.defer_release_until(task)

    try:
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await decoder.run(
                ("synthetic-decoder",),
                input_bytes=b"synthetic-source",
                deadline_monotonic=lease.deadline_monotonic,
                on_reap=record_reaper,
            )
        lease.release()
        assert len(reapers) == 1
        stdout_eof.set()

        for _ in range(100):
            if probe_called.is_set() or reapers[0].done():
                break
            await asyncio.sleep(0.001)
        assert probe_called.is_set(), "successful kill must be followed by process-group verification"
        assert not reapers[0].done(), "a still-existing descendant group must keep the reaper pending"
        expected_unhealthy_count = initial_health + 1
        expected_permit_count = initial_permits - 1
        assert expected_unhealthy_count == speaker_excerpt_service._UNCONFIRMED_DECODERS
        assert expected_permit_count == speaker_excerpt_service._PROCESS_PERMITS._value

        group_gone.set()
        await reapers[0]
        assert initial_health == speaker_excerpt_service._UNCONFIRMED_DECODERS
        assert initial_permits == speaker_excerpt_service._PROCESS_PERMITS._value
    finally:
        stdout_eof.set()
        group_gone.set()
        for reaper in reapers:
            if not reaper.done():
                with suppress(BaseException):
                    await reaper
        lease.release()
        speaker_excerpt_service._UNCONFIRMED_DECODERS = initial_health
        if speaker_excerpt_service._PROCESS_PERMITS._value < initial_permits:
            speaker_excerpt_service._PROCESS_PERMITS.release()


@pytest.mark.asyncio
async def test_managed_decoder_retains_permit_when_group_exit_cannot_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        speaker_excerpt_service,
        "PROCESS_GROUP_CONFIRMATION_TIMEOUT_SECONDS",
        0.01,
    )
    events: list[str] = []
    decoder, process = managed_decoder_for_test(
        events,
        confirm_exit_on_kill=False,
        process_group_exists=lambda _pid: True,
        monotonic=time.monotonic,
    )
    reapers: list[asyncio.Task[bool]] = []
    initial_health = speaker_excerpt_service._UNCONFIRMED_DECODERS
    initial_permits = speaker_excerpt_service._PROCESS_PERMITS._value
    await speaker_excerpt_service._PROCESS_PERMITS.acquire()
    lease = speaker_excerpt_service._OperationLease(time.monotonic() + 0.01)

    def record_reaper(task: asyncio.Task[bool]) -> None:
        reapers.append(task)
        lease.defer_release_until(task)

    try:
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await decoder.run(
                ("synthetic-decoder",),
                input_bytes=b"synthetic-source",
                deadline_monotonic=lease.deadline_monotonic,
                on_reap=record_reaper,
            )
        lease.release()
        assert len(reapers) == 1
        process.exited.set()
        assert await reapers[0] is False
        expected_unhealthy_count = initial_health + 1
        expected_permit_count = initial_permits - 1
        assert expected_unhealthy_count == speaker_excerpt_service._UNCONFIRMED_DECODERS
        assert expected_permit_count == speaker_excerpt_service._PROCESS_PERMITS._value
    finally:
        process.exited.set()
        for reaper in reapers:
            if not reaper.done():
                with suppress(BaseException):
                    await reaper
        lease.release()
        speaker_excerpt_service._UNCONFIRMED_DECODERS = initial_health
        if speaker_excerpt_service._PROCESS_PERMITS._value < initial_permits:
            speaker_excerpt_service._PROCESS_PERMITS.release()


@pytest.mark.asyncio
async def test_managed_decoder_hard_kills_and_reaps_before_discarding_timed_out_output() -> None:
    events: list[str] = []
    decoder, _process = managed_decoder_for_test(events, confirm_exit_on_kill=True)

    with pytest.raises((TimeoutError, ValueError, RuntimeError)) as error:
        await decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.1,
        )

    assert events[:2] == ["spawned_process_group", "communicate_started"]
    assert events.index("killed_process_group") < events.index("communicate_finished")
    assert events.index("communicate_finished") < events.index("wait_started")
    assert events.index("wait_started") < events.index("wait_confirmed")
    assert "synthetic-partial-output" not in str(error.value)
    assert "private-decoder-diagnostic" not in str(error.value)


@pytest.mark.asyncio
async def test_decoder_returns_on_timeout_and_reaps_in_background_without_releasing_health() -> None:
    events: list[str] = []
    decoder, process = managed_decoder_for_test(events, confirm_exit_on_kill=False)
    operation = asyncio.create_task(
        decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=0.1,
        )
    )

    await asyncio.sleep(0.12)
    assert operation.done(), "request must return when deadline expires, not wait for reap"
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await operation
    assert events == [
        "spawned_process_group",
        "communicate_started",
        "killed_process_group",
    ]
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1

    process.exited.set()
    for _ in range(100):
        if speaker_excerpt_service._UNCONFIRMED_DECODERS == 0:
            break
        await asyncio.sleep(0.005)
    assert events.index("communicate_finished") < events.index("wait_started")
    assert events.index("wait_started") < events.index("wait_confirmed")
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 0


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_decoder_reap() -> None:
    events: list[str] = []
    decoder, process = managed_decoder_for_test(events, confirm_exit_on_kill=False)
    operation = asyncio.create_task(
        decoder.run(
            ("synthetic-decoder",),
            input_bytes=b"synthetic-source",
            deadline_monotonic=100.0,
        )
    )
    for _ in range(100):
        if "communicate_started" in events:
            break
        await asyncio.sleep(0.001)
    assert "communicate_started" in events
    operation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, timeout=0.1)
    operation.cancel()
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
    assert "wait_started" not in events
    process.exited.set()
    for _ in range(100):
        if speaker_excerpt_service._UNCONFIRMED_DECODERS == 0:
            break
        await asyncio.sleep(0.001)
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
    assert events.index("communicate_finished") < events.index("wait_started")
    assert "wait_confirmed" in events


@pytest.mark.asyncio
async def test_service_holds_permit_until_managed_decoder_exit_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    keyring: ExcerptKeyring,
) -> None:
    monkeypatch.setattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS", 0.2, raising=False)
    events: list[str] = []
    managed_decoder, process = managed_decoder_for_test(
        events, confirm_exit_on_kill=False, monotonic=time.monotonic
    )
    decode_calls: list[int] = []

    def decode_interval(
        start_ms: int,
        _end_ms: int,
        **_kwargs: Any,
    ) -> tuple[str, ...]:
        decode_calls.append(start_ms)
        return ("synthetic-decoder",)

    excerpt_service = service(
        decode_interval=decode_interval,
        decoder=managed_decoder,
        keyring=keyring,
    )
    first_request = asyncio.create_task(
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, 1_000)],
        )
    )
    await asyncio.sleep(0.25)
    assert first_request.done(), "deadline must return without waiting for process reap"
    with pytest.raises((TimeoutError, ValueError, RuntimeError)):
        await first_request
    assert events == [
        "spawned_process_group",
        "communicate_started",
        "killed_process_group",
    ]
    assert "wait_started" not in events
    assert speaker_excerpt_service._UNCONFIRMED_DECODERS == 1
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 1

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
    for _ in range(100):
        if (
            speaker_excerpt_service._UNCONFIRMED_DECODERS == 0
            and speaker_excerpt_service._PROCESS_PERMITS._value == 2
        ):
            break
        await asyncio.sleep(0.005)
    assert events.index("communicate_finished") < events.index("wait_started")
    assert "wait_confirmed" in events
    assert speaker_excerpt_service._PROCESS_PERMITS._value == 2
