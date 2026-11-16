"""Thumbnail generation, recording of outcomes and the one-at-a-time sweep."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, RecordingMediaSource, SessionRecording
from app.infra.object_store import ObjectStore
from app.thumbnails import service
from app.thumbnails.ffmpeg import MediaProbe, MediaToolError
from app.thumbnails.service import generate_thumbnail, process_pending, run_thumbnail_sweeper, thumbnail_key

JPEG = b"\xff\xd8\xff\xe0frame"


class MemoryStore(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.urls: list[str] = []
        self.fail_save = False

    async def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        if self.fail_save:
            raise OSError("object store down")
        self.objects[key] = content
        return key

    async def get(self, reference: str) -> bytes:
        return self.objects[reference]

    async def delete(self, reference: str) -> None:
        self.objects.pop(reference, None)

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        self.urls.append(reference)
        return f"http://storage.invalid/{reference}?sig=secret"


class FakeMedia:
    """Replaces probe_media / extract_best_frame and records what they were asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.probe: MediaProbe | Exception = MediaProbe(duration_seconds=1800.0, has_video=True)
        self.frame: bytes | None | Exception = JPEG
        self.frame_calls: list[tuple[float | None, float]] = []
        self.probe_calls = 0
        monkeypatch.setattr(service, "probe_media", self._probe)
        monkeypatch.setattr(service, "extract_best_frame", self._frame)

    async def _probe(self, url: str) -> MediaProbe:
        self.probe_calls += 1
        if isinstance(self.probe, Exception):
            raise self.probe
        return self.probe

    async def _frame(self, url: str, duration: float | None, offset: float = 0.0) -> bytes | None:
        self.frame_calls.append((duration, offset))
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch) -> FakeMedia:
    return FakeMedia(monkeypatch)


async def add_recording(
    factory: async_sessionmaker[AsyncSession],
    *,
    presence: str = "muxed",
    duration: int = 1800,
    finished_offset: int = 0,
    video_offset_ms: int | None = None,
    state: str | None = None,
    recorded_at_source: str | None = "capture",  # a known recording date: no probe for it
) -> tuple[str, str]:
    meeting_id, recording_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="transcribing",
            created_by="owner", created_at=now, recorded_at=now, recorded_at_source=recorded_at_source,
        ))
        await session.flush()
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
            capture_origin="web_upload", audio_ref=f"recordings/{meeting_id}/a/audio",
            video_ref=f"recordings/{meeting_id}/a/video" if presence == "separate" else None,
            duration_seconds=duration, interrupted=False,
            finished_at=now - timedelta(seconds=finished_offset), video_presence=presence,
            thumbnail_state=state,
        ))
        session.add(RecordingMediaSource(
            id=str(uuid.uuid4()), recording_id=recording_id, kind="audio",
            object_ref=f"recordings/{meeting_id}/a/audio", quality_label="Original",
        ))
        if presence == "separate":
            session.add(RecordingMediaSource(
                id=str(uuid.uuid4()), recording_id=recording_id, kind="video",
                object_ref=f"recordings/{meeting_id}/a/video", video_offset_ms=video_offset_ms,
                quality_label="Original",
            ))
    return meeting_id, recording_id


async def row(factory: async_sessionmaker[AsyncSession], recording_id: str) -> SessionRecording:
    async with factory() as session:
        recording = await session.get(SessionRecording, recording_id)
        assert recording is not None
        return recording


@pytest.mark.asyncio
async def test_a_muxed_video_gets_a_stored_frame_next_to_the_recording(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    store = MemoryStore()
    meeting_id, recording_id = await add_recording(session_factory)

    assert await generate_thumbnail(session_factory, store, recording_id) == "ready"

    key = thumbnail_key(meeting_id, recording_id)
    assert key == f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg"
    assert store.objects == {key: JPEG}
    saved = await row(session_factory, recording_id)
    assert (saved.thumbnail_state, saved.thumbnail_ref) == ("ready", key)
    assert store.urls == [f"recordings/{meeting_id}/a/audio"]
    assert media.frame_calls == [(1800.0, 0.0)]


@pytest.mark.asyncio
async def test_a_recording_declared_without_video_never_touches_ffmpeg(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    store = MemoryStore()
    _, recording_id = await add_recording(session_factory, presence="absent")

    assert await generate_thumbnail(session_factory, store, recording_id) == "audio_only"

    assert media.probe_calls == 0 and media.frame_calls == [] and store.urls == []
    saved = await row(session_factory, recording_id)
    assert (saved.thumbnail_state, saved.thumbnail_ref) == ("audio_only", None)


@pytest.mark.asyncio
async def test_media_without_a_video_stream_is_audio_only(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    media.probe = MediaProbe(duration_seconds=90.0, has_video=False)
    _, recording_id = await add_recording(session_factory, presence="unknown")

    assert await generate_thumbnail(session_factory, MemoryStore(), recording_id) == "audio_only"
    assert media.frame_calls == []


@pytest.mark.asyncio
async def test_unknown_container_duration_falls_back_to_the_recorded_duration_then_to_unknown(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    media.probe = MediaProbe(duration_seconds=None, has_video=True)
    _, with_duration = await add_recording(session_factory, duration=240)
    _, legacy_zero = await add_recording(session_factory, duration=0)

    await generate_thumbnail(session_factory, MemoryStore(), with_duration)
    await generate_thumbnail(session_factory, MemoryStore(), legacy_zero)

    assert media.frame_calls == [(240.0, 0.0), (None, 0.0)]


@pytest.mark.asyncio
async def test_the_probed_duration_wins_over_the_stored_zero(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    media.probe = MediaProbe(duration_seconds=1234.5, has_video=True)
    _, recording_id = await add_recording(session_factory, duration=0)

    await generate_thumbnail(session_factory, MemoryStore(), recording_id)

    assert media.frame_calls == [(1234.5, 0.0)]


@pytest.mark.asyncio
async def test_a_separate_video_is_read_from_the_video_object_with_its_offset(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    store = MemoryStore()
    meeting_id, recording_id = await add_recording(session_factory, presence="separate", video_offset_ms=1500)

    assert await generate_thumbnail(session_factory, store, recording_id) == "ready"

    assert store.urls == [f"recordings/{meeting_id}/a/video"]
    assert media.frame_calls == [(1800.0, 1.5)]


@pytest.mark.asyncio
async def test_a_separate_video_without_a_usable_source_is_unavailable(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    _, recording_id = await add_recording(session_factory, presence="separate", video_offset_ms=None)

    assert await generate_thumbnail(session_factory, MemoryStore(), recording_id) == "unavailable"
    assert media.probe_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["probe", "no_frame", "frame_error"])
async def test_media_problems_are_recorded_as_unavailable_and_do_not_fail_the_meeting(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, failure: str
) -> None:
    if failure == "probe":
        media.probe = MediaToolError("ffprobe exited with 1")
    elif failure == "no_frame":
        media.frame = None
    else:
        media.frame = MediaToolError("ffmpeg exited with 1")
    store = MemoryStore()
    meeting_id, recording_id = await add_recording(session_factory)

    assert await generate_thumbnail(session_factory, store, recording_id) == "unavailable"

    saved = await row(session_factory, recording_id)
    assert (saved.thumbnail_state, saved.thumbnail_ref) == ("unavailable", None)
    assert store.objects == {}
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "transcribing"


@pytest.mark.asyncio
async def test_infrastructure_errors_propagate_and_leave_the_recording_pending(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    store = MemoryStore()
    store.fail_save = True
    _, recording_id = await add_recording(session_factory)

    with pytest.raises(OSError):
        await generate_thumbnail(session_factory, store, recording_id)

    assert (await row(session_factory, recording_id)).thumbnail_state is None


@pytest.mark.asyncio
async def test_a_recording_deleted_while_its_frame_is_cut_leaves_no_object_behind(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore()
    _, recording_id = await add_recording(session_factory)

    async def delete_during_extraction(url: str, duration: float | None, offset: float = 0.0) -> bytes:
        async with session_factory() as session, session.begin():
            recording = await session.get(SessionRecording, recording_id)
            assert recording is not None
            await session.delete(recording)
        return JPEG

    monkeypatch.setattr(service, "extract_best_frame", delete_during_extraction)
    await generate_thumbnail(session_factory, store, recording_id)

    assert store.objects == {}


@pytest.mark.asyncio
async def test_a_missing_recording_is_a_no_op(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    assert await generate_thumbnail(session_factory, MemoryStore(), "does-not-exist") is None


@pytest.mark.asyncio
async def test_the_sweep_handles_pending_recordings_one_at_a_time_newest_first(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    running = 0
    peak = 0
    real_generate = service.generate_thumbnail

    async def tracked(factory: Any, store: Any, recording_id: str) -> Any:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        order.append(recording_id)
        try:
            return await real_generate(factory, store, recording_id)
        finally:
            running -= 1

    monkeypatch.setattr(service, "generate_thumbnail", tracked)
    _, oldest = await add_recording(session_factory, finished_offset=300)
    _, newest = await add_recording(session_factory, finished_offset=10)
    _, done = await add_recording(session_factory, state="ready")

    tally = await process_pending(session_factory, MemoryStore())

    assert order == [newest, oldest]
    assert done not in order
    assert peak == 1
    assert tally == {"ready": 2}


@pytest.mark.asyncio
async def test_an_infrastructure_error_does_not_stop_the_sweep_and_is_not_retried_in_it(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    store = MemoryStore()
    _, first = await add_recording(session_factory, finished_offset=10)
    _, second = await add_recording(session_factory, finished_offset=20)
    original = store.save
    calls: list[str] = []

    async def flaky_save(key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        calls.append(key)
        if first in key:
            raise OSError("object store down")
        return await original(key, content, content_type)

    store.save = flaky_save  # type: ignore[method-assign]
    failed: set[str] = set()

    tally = await process_pending(session_factory, store, failed=failed)

    assert tally == {"error": 1, "ready": 1}
    assert failed == {first}
    assert (await row(session_factory, first)).thumbnail_state is None
    assert (await row(session_factory, second)).thumbnail_state == "ready"
    assert len(calls) == 2
    # The next sweep skips the failed one until the worker restarts.
    assert await process_pending(session_factory, store, failed=failed) == {}


@pytest.mark.asyncio
async def test_retry_unavailable_is_opt_in(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    _, recording_id = await add_recording(session_factory, state="unavailable")
    store = MemoryStore()

    assert await process_pending(session_factory, store) == {}
    assert await process_pending(session_factory, store, include_unavailable=True) == {"ready": 1}
    assert (await row(session_factory, recording_id)).thumbnail_state == "ready"
    # A second pass finds nothing to do: the run is idempotent.
    assert await process_pending(session_factory, store, include_unavailable=True) == {}


@pytest.mark.asyncio
async def test_limit_stops_the_run(session_factory: async_sessionmaker[AsyncSession], media: FakeMedia) -> None:
    for offset in (1, 2, 3):
        await add_recording(session_factory, finished_offset=offset)

    assert await process_pending(session_factory, MemoryStore(), limit=2) == {"ready": 2}


@pytest.mark.asyncio
async def test_the_sweeper_survives_a_failing_cycle(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    cycles = 0

    async def explode(*args: Any, **kwargs: Any) -> None:
        nonlocal cycles
        cycles += 1
        raise RuntimeError("database restarting")

    monkeypatch.setattr(service, "process_pending", explode)
    task = asyncio.create_task(run_thumbnail_sweeper(session_factory, MemoryStore(), interval_seconds=1))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cycles == 1


def test_sweep_interval_reads_the_environment_with_a_safe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THUMBNAIL_SWEEP_INTERVAL_SECONDS", raising=False)
    assert service.sweep_interval_seconds() == 30
    for raw, expected in (("5", 5), ("0", 30), ("-3", 30), ("soon", 30)):
        monkeypatch.setenv("THUMBNAIL_SWEEP_INTERVAL_SECONDS", raw)
        assert service.sweep_interval_seconds() == expected
