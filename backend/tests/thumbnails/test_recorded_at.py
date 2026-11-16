"""The recording date read from the media's own metadata, while it is already being probed."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SessionRecording
from app.thumbnails import recorded_at as backfill
from app.thumbnails import service
from app.thumbnails.ffmpeg import MediaProbe, MediaToolError, parse_probe, probe_command
from app.thumbnails.service import generate_thumbnail
from tests.thumbnails.test_service import FakeMedia, MemoryStore, add_recording

CREATED = datetime(2024, 3, 5, 10, 20, 30, tzinfo=UTC)


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch) -> FakeMedia:
    return FakeMedia(monkeypatch)


def _probe_json(tags: dict[str, str] | None) -> bytes:
    document: dict[str, object] = {"streams": [{"codec_type": "video"}], "format": {"duration": "10.0"}}
    if tags is not None:
        document["format"] = {"duration": "10.0", "tags": tags}
    return json.dumps(document).encode()


# --- Reading the tag -----------------------------------------------------------------------------


def test_creation_time_tag_of_mp4_mov_and_webm_is_read() -> None:
    probe = parse_probe(_probe_json({"creation_time": "2024-03-05T10:20:30.000000Z"}))
    assert probe.creation_time == CREATED


def test_the_quicktime_date_wins_and_keeps_its_real_offset() -> None:
    probe = parse_probe(_probe_json({
        "creation_time": "2024-03-05T10:20:30.000000Z",
        "com.apple.quicktime.creationdate": "2024-03-05T05:20:30-0500",
    }))
    assert probe.creation_time == datetime(2024, 3, 5, 10, 20, 30, tzinfo=UTC)
    other = parse_probe(_probe_json({"com.apple.quicktime.creationdate": "2024-03-05T08:00:00+0200"}))
    assert other.creation_time == datetime(2024, 3, 5, 6, 0, tzinfo=UTC)


def test_matroska_date_tag_is_read_in_any_letter_case() -> None:
    assert parse_probe(_probe_json({"DATE": "2023-01-02"})).creation_time == datetime(2023, 1, 2, tzinfo=UTC)
    assert parse_probe(_probe_json({"date": "2023-01-02"})).creation_time == datetime(2023, 1, 2, tzinfo=UTC)


@pytest.mark.parametrize("tags", [None, {}, {"title": "Quarterly"}, {"creation_time": "garbage"}])
def test_missing_or_unreadable_tags_give_no_date(tags: dict[str, str] | None) -> None:
    assert parse_probe(_probe_json(tags)).creation_time is None


def test_only_the_date_tags_are_requested_from_ffprobe() -> None:
    command = probe_command("http://storage.invalid/x")
    entries = command[command.index("-show_entries") + 1]
    assert "format_tags=com.apple.quicktime.creationdate,creation_time,date" in entries
    assert "location" not in entries and "title" not in entries


# --- Applying it ---------------------------------------------------------------------------------


async def _meeting(factory: async_sessionmaker[AsyncSession], meeting_id: str) -> Meeting:
    async with factory() as session:
        meeting = await session.get(Meeting, meeting_id)
    assert meeting is not None
    return meeting


@pytest.mark.asyncio
async def test_a_probed_video_upgrades_a_received_date_to_file_metadata(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    meeting_id, recording_id = await add_recording(session_factory, recorded_at_source="received")
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=CREATED)

    await generate_thumbnail(session_factory, MemoryStore(), recording_id)

    meeting = await _meeting(session_factory, meeting_id)
    assert meeting.recorded_at_source == "file_metadata"
    assert meeting.recorded_at is not None and meeting.recorded_at.replace(tzinfo=UTC) == CREATED
    assert media.probe_calls == 1  # the same probe that finds the frame time: no extra pass


@pytest.mark.asyncio
async def test_the_container_date_beats_the_browser_file_date(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    meeting_id, recording_id = await add_recording(session_factory, recorded_at_source="file_modified")
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=CREATED)
    await generate_thumbnail(session_factory, MemoryStore(), recording_id)
    assert (await _meeting(session_factory, meeting_id)).recorded_at_source == "file_metadata"


@pytest.mark.asyncio
async def test_a_capture_date_is_never_replaced_by_a_tag(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    meeting_id, recording_id = await add_recording(session_factory, recorded_at_source="capture")
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=CREATED)
    await generate_thumbnail(session_factory, MemoryStore(), recording_id)
    assert (await _meeting(session_factory, meeting_id)).recorded_at_source == "capture"


@pytest.mark.asyncio
@pytest.mark.parametrize("creation", [None, datetime(1904, 1, 1, tzinfo=UTC), datetime(2999, 1, 1, tzinfo=UTC)])
async def test_a_missing_or_implausible_tag_keeps_the_current_date(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, creation: datetime | None
) -> None:
    meeting_id, recording_id = await add_recording(session_factory, recorded_at_source="file_modified")
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=creation)
    await generate_thumbnail(session_factory, MemoryStore(), recording_id)
    assert (await _meeting(session_factory, meeting_id)).recorded_at_source == "file_modified"


@pytest.mark.asyncio
async def test_an_audio_only_upload_is_probed_for_its_date_only_when_the_date_can_improve(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    media.probe = MediaProbe(duration_seconds=60.0, has_video=False, creation_time=CREATED)
    meeting_id, recording_id = await add_recording(
        session_factory, presence="absent", recorded_at_source="received"
    )

    assert await generate_thumbnail(session_factory, MemoryStore(), recording_id) == "audio_only"

    assert (await _meeting(session_factory, meeting_id)).recorded_at_source == "file_metadata"
    assert media.probe_calls == 1 and media.frame_calls == []


@pytest.mark.asyncio
async def test_extension_recordings_are_never_probed_for_a_date(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    meeting_id, recording_id = await add_recording(
        session_factory, presence="absent", recorded_at_source="received"
    )
    async with session_factory() as session, session.begin():
        recording = await session.get(SessionRecording, recording_id)
        assert recording is not None
        recording.capture_origin = "chrome_extension"
    media.probe = MediaProbe(duration_seconds=60.0, has_video=False, creation_time=CREATED)

    await generate_thumbnail(session_factory, MemoryStore(), recording_id)

    assert media.probe_calls == 0
    assert (await _meeting(session_factory, meeting_id)).recorded_at_source == "received"


@pytest.mark.asyncio
async def test_an_unreadable_audio_file_does_not_fail_the_thumbnail_outcome(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia
) -> None:
    media.probe = MediaToolError("bad media")
    _, recording_id = await add_recording(session_factory, presence="absent", recorded_at_source="received")
    assert await generate_thumbnail(session_factory, MemoryStore(), recording_id) == "audio_only"


# --- The on-demand backfill ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_upgrades_old_web_uploads_and_skips_the_rest(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill, "probe_media", service.probe_media)  # the same fake as the service
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=CREATED)
    old, _ = await add_recording(session_factory, recorded_at_source="received")
    tagged_already, _ = await add_recording(session_factory, recorded_at_source="file_metadata")
    captured, _ = await add_recording(session_factory, recorded_at_source="capture")

    tally = await backfill.backfill_recorded_at(session_factory, MemoryStore())

    assert dict(tally) == {"updated": 1}
    assert (await _meeting(session_factory, old)).recorded_at_source == "file_metadata"
    assert (await _meeting(session_factory, tagged_already)).recorded_at_source == "file_metadata"
    assert (await _meeting(session_factory, captured)).recorded_at_source == "capture"
    assert media.probe_calls == 1

    again = await backfill.backfill_recorded_at(session_factory, MemoryStore())  # idempotent
    assert dict(again) == {} and media.probe_calls == 1


@pytest.mark.asyncio
async def test_backfill_counts_files_without_a_tag_and_unreadable_files(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill, "probe_media", service.probe_media)
    await add_recording(session_factory, recorded_at_source="received")
    media.probe = MediaProbe(duration_seconds=60.0, has_video=True, creation_time=None)
    assert dict(await backfill.backfill_recorded_at(session_factory, MemoryStore())) == {"no_creation_date": 1}
    media.probe = MediaToolError("bad media")
    assert dict(await backfill.backfill_recorded_at(session_factory, MemoryStore())) == {"unreadable": 1}


@pytest.mark.asyncio
async def test_backfill_limit_bounds_the_work(
    session_factory: async_sessionmaker[AsyncSession], media: FakeMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill, "probe_media", service.probe_media)
    for _ in range(3):
        await add_recording(session_factory, recorded_at_source="received")
    tally = await backfill.backfill_recorded_at(session_factory, MemoryStore(), limit=2)
    assert sum(tally.values()) == 2
