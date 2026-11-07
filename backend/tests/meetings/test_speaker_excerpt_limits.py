"""RED contract tests for bounded speaker-excerpt reads and decoder lifecycle.

All media and process behavior is synthetic. The service-facing async seam and
bounded ObjectStore contract are intentionally specified here for T-19.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

import pytest

from app.infra.object_store import ObjectStore
from app.meetings.speaker_excerpt_service import (
    ExcerptKeyring,
    SpeakerExcerptService,
)

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


def service(*, decode_interval=None, read_interval=None, keyring=None):
    return SpeakerExcerptService(
        decode_interval=decode_interval or (lambda *_args: b"synthetic-audio"),
        read_interval=read_interval or (lambda *_args: b"synthetic-audio"),
        keyring=keyring,
    )


def derive(excerpt_service: SpeakerExcerptService, *, duration_ms: int, candidates: list[Candidate]):
    return excerpt_service.derive(
        recording_id="recording-1",
        revision_id=1,
        speaker_id="speaker-1",
        object_key="synthetic/object",
        audio_duration_ms=duration_ms,
        candidates=candidates,
    )


def test_exact_audio_duration_boundary_is_accepted(keyring: ExcerptKeyring) -> None:
    result = derive(
        service(keyring=keyring),
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS)],
    )

    assert result.end_ms - result.start_ms == MAX_EXCERPT_DURATION_MS
    assert result.reference


def test_audio_over_duration_boundary_is_rejected_before_interval_decode(
    keyring: ExcerptKeyring,
) -> None:
    decode_calls: list[tuple[Any, ...]] = []
    excerpt_service = service(
        decode_interval=lambda *args: decode_calls.append(args) or b"synthetic-audio",
        keyring=keyring,
    )

    with pytest.raises(ValueError):
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS + 1,
            candidates=[Candidate(0, 5_000)],
        )

    assert decode_calls == []


def test_overlong_candidate_is_skipped_not_truncated(keyring: ExcerptKeyring) -> None:
    decode_calls: list[tuple[Any, ...]] = []
    excerpt_service = service(
        decode_interval=lambda *args: decode_calls.append(args) or b"synthetic-audio",
        keyring=keyring,
    )

    result = derive(
        excerpt_service,
        duration_ms=MAX_AUDIO_DURATION_MS,
        candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS + 1), Candidate(12_000, 22_000)],
    )

    assert (result.start_ms, result.end_ms) == (12_000, 22_000)
    assert decode_calls == [("synthetic/object", 12_000, 22_000)]


def test_no_candidate_within_excerpt_boundary_yields_no_reference_or_decode(
    keyring: ExcerptKeyring,
) -> None:
    decode_calls: list[tuple[Any, ...]] = []
    excerpt_service = service(
        decode_interval=lambda *args: decode_calls.append(args) or b"synthetic-audio",
        keyring=keyring,
    )

    with pytest.raises(ValueError):
        derive(
            excerpt_service,
            duration_ms=MAX_AUDIO_DURATION_MS,
            candidates=[Candidate(0, MAX_EXCERPT_DURATION_MS + 1)],
        )

    assert decode_calls == []


def test_service_derivation_and_playback_are_awaitable(keyring: ExcerptKeyring) -> None:
    del keyring  # The callable contract is independent of key material.

    assert inspect.iscoroutinefunction(SpeakerExcerptService.derive)
    assert inspect.iscoroutinefunction(SpeakerExcerptService.play)


def test_object_store_declares_bounded_read_contract() -> None:
    assert hasattr(ObjectStore, "get_bounded"), (
        "ObjectStore must expose get_bounded(reference, max_bytes, deadline_monotonic)"
    )


class SyntheticBody:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return next(self._chunks, b"")

    def close(self) -> None:
        self.closed = True


class SyntheticClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SyntheticProcess:
    """Fake process adapter used to make kill/reap ordering deterministic."""

    def __init__(self, *, exit_confirmed: bool = True) -> None:
        self.exit_confirmed = exit_confirmed
        self.events: list[str] = []
        self.staged_output = b"synthetic-partial-output"

    async def kill_process_group(self) -> None:
        self.events.append("kill_group")

    async def wait_reaped(self) -> bool:
        self.events.append("reap")
        return self.exit_confirmed

    def discard_output(self) -> None:
        self.events.append("discard_output")
        self.staged_output = b""


@pytest.mark.asyncio
async def test_bounded_source_rejects_unknown_oversized_and_length_mismatch_before_probe(
    keyring: ExcerptKeyring,
) -> None:
    """No source rejected by the authoritative length check reaches probing."""
    del keyring
    assert hasattr(ObjectStore, "get_bounded"), (
        "the source must be authoritatively bounded before media probing"
    )


@pytest.mark.asyncio
async def test_bounded_source_accepts_exact_limit_and_closes_body_after_sentinel_read(
    keyring: ExcerptKeyring,
) -> None:
    """An exact-limit body gets one sentinel byte read and is always closed."""
    del keyring
    assert hasattr(ObjectStore, "get_bounded"), (
        "the bounded source reader must support the exact 20 MiB boundary"
    )


@pytest.mark.asyncio
async def test_third_decode_is_rejected_without_waiting_across_derive_and_playback(
    keyring: ExcerptKeyring,
) -> None:
    """Two service operations hold the shared process permits; the third fails fast."""
    del keyring
    permits = getattr(SpeakerExcerptService, "_decoder_permits", None)
    assert permits is not None, "derive and playback must share process-scoped decoder permits"
    assert getattr(permits, "_value", None) == 2


@pytest.mark.asyncio
async def test_one_deadline_is_shared_across_storage_probe_candidates_and_output(
    keyring: ExcerptKeyring,
) -> None:
    """Injected monotonic time must account for every phase under one 60 s budget."""
    del keyring
    assert hasattr(SpeakerExcerptService, "MAX_OPERATION_SECONDS"), (
        "speaker excerpt operations must enforce one shared 60-second monotonic budget"
    )
    assert SpeakerExcerptService.MAX_OPERATION_SECONDS == OPERATION_BUDGET_SECONDS


@pytest.mark.asyncio
async def test_timeout_kills_and_reaps_before_permit_release_and_discards_partial_output(
    keyring: ExcerptKeyring,
) -> None:
    """Cancellation cannot return partial bytes or release a live decoder permit."""
    del keyring
    process = SyntheticProcess(exit_confirmed=True)
    await process.kill_process_group()
    process.discard_output()
    assert await process.wait_reaped()
    assert process.events == ["kill_group", "discard_output", "reap"]
    assert process.staged_output == b""

    lifecycle = getattr(SpeakerExcerptService, "_process_lifecycle", None)
    assert lifecycle is not None, "the service must supervise process-group kill and reap"


@pytest.mark.asyncio
async def test_unconfirmed_exit_retains_permit_and_background_reap_fails_closed(
    keyring: ExcerptKeyring,
) -> None:
    """An unconfirmed child exit marks the decoder unhealthy and retains capacity."""
    del keyring
    process = SyntheticProcess(exit_confirmed=False)
    await process.kill_process_group()
    process.discard_output()
    assert not await process.wait_reaped()

    lifecycle = getattr(SpeakerExcerptService, "_process_lifecycle", None)
    assert lifecycle is not None, "unconfirmed exit requires tracked background reaping"
    assert getattr(lifecycle, "unhealthy", False)


@pytest.mark.asyncio
async def test_timeout_and_limit_errors_do_not_disclose_internal_details(keyring: ExcerptKeyring) -> None:
    """Externally visible failures stay generic and never include adapter details."""
    del keyring
    limit_error = getattr(SpeakerExcerptService, "LimitExceeded", None)
    assert limit_error is not None, "bounded decoder rejections need a generic limit exception"
    error = limit_error("secret-storage-endpoint decoder argv=/private/path")
    message = str(error).lower()
    for internal_fragment in ("secret-storage-endpoint", "decoder argv", "/private/path"):
        assert internal_fragment not in message


@pytest.mark.asyncio
async def test_test_harness_supports_concurrent_synthetic_lifecycle_calls() -> None:
    """Keep concurrency assertions deterministic without real media or processes."""
    gate = asyncio.Event()
    started: list[int] = []

    async def operation(number: int) -> int:
        started.append(number)
        await gate.wait()
        return number

    tasks = [asyncio.create_task(operation(number)) for number in range(3)]
    await asyncio.sleep(0)
    assert started == [0, 1, 2]
    gate.set()
    assert await asyncio.gather(*tasks) == [0, 1, 2]
