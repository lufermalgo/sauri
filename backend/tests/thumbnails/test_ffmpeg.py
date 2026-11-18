"""ffmpeg/ffprobe invocation: arguments, timeouts and safe error handling (subprocess mocked)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from app.thumbnails import ffmpeg
from app.thumbnails.ffmpeg import (
    MediaToolError,
    extract_best_frame,
    extract_frame,
    frame_command,
    parse_probe,
    probe_command,
    probe_media,
)

SIGNED_URL = "http://storage.internal:9000/bucket/recordings/m/r/audio?X-Amz-Signature=secret-signature"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class FakeProcess:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang: bool = False) -> None:
        self._stdout, self._stderr, self._code, self._hang = stdout, stderr, returncode, hang
        self.returncode: int | None = None if hang else returncode
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else -1


class Spawner:
    """Replaces asyncio.create_subprocess_exec and records every spawn."""

    def __init__(self, *processes: FakeProcess) -> None:
        self.processes = list(processes)
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def __call__(self, *args: str, **kwargs: Any) -> FakeProcess:
        self.calls.append((args, kwargs))
        return self.processes.pop(0)


def install(monkeypatch: pytest.MonkeyPatch, *processes: FakeProcess) -> Spawner:
    spawner = Spawner(*processes)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawner)
    return spawner


def test_frame_command_seeks_before_the_input_and_scales_to_a_single_jpeg() -> None:
    command = frame_command(SIGNED_URL, 600.0)
    assert command[0] == "ffmpeg"
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "600.000"
    assert command[command.index("-i") + 1] == SIGNED_URL
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[command.index("-vf") + 1] == "scale=320:-2"
    assert command[command.index("-f") + 1] == "mjpeg"
    assert command[-1] == "pipe:1"
    assert "-nostdin" in command and "-an" in command


def test_both_tools_restrict_protocols_and_formats_for_untrusted_media() -> None:
    for command in (frame_command(SIGNED_URL, 1.0), probe_command(SIGNED_URL)):
        protocols = command[command.index("-protocol_whitelist") + 1].split(",")
        assert "file" not in protocols and "concat" not in protocols
        assert {"http", "https"} <= set(protocols)
        formats = command[command.index("-format_whitelist") + 1].split(",")
        assert "hls" not in formats and "concat" not in formats
        assert {"mov", "mp4", "matroska", "webm", "mp3", "wav"} <= set(formats)


@pytest.mark.asyncio
async def test_extract_frame_runs_without_a_shell_or_stdin_and_returns_the_jpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawner = install(monkeypatch, FakeProcess(stdout=JPEG))
    assert await extract_frame(SIGNED_URL, 12.5) == JPEG
    args, kwargs = spawner.calls[0]
    assert args == tuple(frame_command(SIGNED_URL, 12.5))
    assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
    assert "shell" not in kwargs


@pytest.mark.asyncio
async def test_extract_frame_rejects_output_that_is_not_a_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeProcess(stdout=b"not an image"))
    with pytest.raises(MediaToolError):
        await extract_frame(SIGNED_URL, 1.0)


@pytest.mark.asyncio
async def test_extract_frame_rejects_an_oversized_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeProcess(stdout=JPEG + b"\x00" * ffmpeg.MAX_FRAME_BYTES))
    with pytest.raises(MediaToolError):
        await extract_frame(SIGNED_URL, 1.0)


@pytest.mark.asyncio
async def test_a_nonzero_exit_is_a_media_error_that_never_carries_the_signed_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = f"Error opening input {SIGNED_URL}: Server returned 403 Forbidden\nmore".encode()
    install(monkeypatch, FakeProcess(stderr=stderr, returncode=1))
    with pytest.raises(MediaToolError) as caught:
        await extract_frame(SIGNED_URL, 1.0)
    assert "secret-signature" not in str(caught.value)
    assert "storage.internal" not in str(caught.value)
    assert "<url>" in str(caught.value)


@pytest.mark.asyncio
async def test_a_hung_ffmpeg_is_killed_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    hung = FakeProcess(hang=True)
    install(monkeypatch, hung)
    monkeypatch.setattr(ffmpeg, "EXTRACT_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(MediaToolError, match="timed out"):
        await extract_frame(SIGNED_URL, 1.0)
    assert hung.killed


@pytest.mark.asyncio
async def test_a_cancelled_run_still_kills_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    hung = FakeProcess(hang=True)
    install(monkeypatch, hung)
    task = asyncio.create_task(extract_frame(SIGNED_URL, 1.0))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hung.killed


@pytest.mark.asyncio
async def test_best_frame_falls_back_to_the_next_moment_when_a_seek_yields_no_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawner = install(monkeypatch, FakeProcess(returncode=234), FakeProcess(stdout=JPEG))
    assert await extract_best_frame(SIGNED_URL, 600.0) == JPEG
    seeks = [args[args.index("-ss") + 1] for args, _ in spawner.calls]
    assert seeks == ["600.000", "300.000"]


@pytest.mark.asyncio
async def test_best_frame_gives_up_quietly_after_the_candidates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    spawner = install(monkeypatch, *[FakeProcess(returncode=1, stderr=SIGNED_URL.encode()) for _ in range(3)])
    with caplog.at_level(logging.DEBUG):
        assert await extract_best_frame(SIGNED_URL, None) is None
    assert len(spawner.calls) == 2  # unknown duration: minute 10, then the start
    assert "secret-signature" not in caplog.text


@pytest.mark.asyncio
async def test_a_separate_video_is_seeked_by_its_offset_and_never_before_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawner = install(monkeypatch, FakeProcess(stdout=JPEG), FakeProcess(stdout=JPEG))
    await extract_best_frame(SIGNED_URL, 3600.0, offset_seconds=2.5)
    await extract_best_frame(SIGNED_URL, 4.0, offset_seconds=10.0)
    seeks = [args[args.index("-ss") + 1] for args, _ in spawner.calls]
    assert seeks == ["597.500", "0.000"]


def probe_output(**format_fields: Any) -> bytes:
    streams = [{"codec_type": "video", "disposition": {"attached_pic": 0}}]
    return json.dumps({"streams": streams, "format": format_fields}).encode()


def test_probe_reads_duration_and_video_presence() -> None:
    probe = parse_probe(probe_output(duration="754.321000"))
    assert probe.duration_seconds == pytest.approx(754.321)
    assert probe.has_video


@pytest.mark.parametrize("fields", [{}, {"duration": "N/A"}, {"duration": "0.000000"}, {"duration": "nan"}])
def test_probe_treats_a_missing_or_unusable_duration_as_unknown(fields: dict[str, str]) -> None:
    assert parse_probe(probe_output(**fields)).duration_seconds is None


def test_probe_audio_only_and_cover_art_have_no_video() -> None:
    audio = json.dumps({"streams": [{"codec_type": "audio", "disposition": {"attached_pic": 0}}], "format": {}})
    cover = json.dumps({"streams": [
        {"codec_type": "audio", "disposition": {"attached_pic": 0}},
        {"codec_type": "video", "disposition": {"attached_pic": 1}},
    ], "format": {"duration": "30"}})
    assert not parse_probe(audio.encode()).has_video
    assert not parse_probe(cover.encode()).has_video


def test_probe_rejects_garbage() -> None:
    with pytest.raises(MediaToolError):
        parse_probe(b"<html>")
    with pytest.raises(MediaToolError):
        parse_probe(b"[1, 2]")


@pytest.mark.asyncio
async def test_probe_media_reports_a_tool_failure_without_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeProcess(stderr=f"{SIGNED_URL}: Invalid data".encode(), returncode=1))
    with pytest.raises(MediaToolError) as caught:
        await probe_media(SIGNED_URL)
    assert "secret-signature" not in str(caught.value)


def test_local_tools_allow_files_but_not_network_or_playlists(tmp_path) -> None:
    path = str(tmp_path / "video")
    for command in (probe_command(path), frame_command(path, 1.0)):
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        formats = command[command.index("-format_whitelist") + 1].split(",")
        assert "hls" not in formats and "concat" not in formats


async def test_local_media_paths_are_redacted_on_error(monkeypatch, tmp_path) -> None:
    path = str(tmp_path / "private-meeting/video")
    install(monkeypatch, FakeProcess(stderr=f"Error opening input {path}".encode(), returncode=1))
    with pytest.raises(MediaToolError) as caught:
        await probe_media(path)
    assert path not in str(caught.value)
    assert "<media>" in str(caught.value)


async def test_real_tools_can_probe_and_extract_local_file(tmp_path) -> None:
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are not installed")
    path = tmp_path / "video"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
        "-c:v", "mpeg4", "-f", "mp4", str(path),
    ], check=True, capture_output=True, timeout=30)
    probe = await probe_media(str(path))
    assert probe.has_video and probe.duration_seconds == 1.0
    frame = await extract_frame(str(path), 0.0)
    assert frame.startswith(b"\xff\xd8\xff")
    assert path.exists()
