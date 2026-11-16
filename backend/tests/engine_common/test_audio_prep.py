"""Audio preparation for external providers, with synthetic audio only (tones, noise and silence).

Planning tests need no binary. Encoding tests need real ffmpeg/ffprobe and are skipped without them.
The real VAD binary is not exercised: tones are not speech, so VAD output is simulated.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sauri_engine_common.external import audio_prep
from sauri_engine_common.external.audio_prep import (
    AudioPrepError,
    plan_parts,
    prepare_audio,
    vad_cli_runner,
)
from sauri_engine_common.external.errors import ProviderError

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe are not installed"
)
RATE = 16000
_TONE = array("h", (round(12000 * math.sin(2 * math.pi * 440 * i / RATE)) for i in range(RATE)))
_QUIET = array("h", (x // 200 for x in _TONE))
_SILENCE = array("h", [0]) * RATE


def write_wav(path: Path, spec: list[tuple[str, int]]) -> list[tuple[int, int]]:
    """Write ``[(kind, ms)]`` (tone, quiet or silence) as PCM16 mono 16 kHz; return the tone intervals in ms."""
    blocks = {"tone": _TONE, "quiet": _QUIET, "silence": _SILENCE}
    tones: list[tuple[int, int]] = []
    cursor = 0
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        for kind, ms in spec:
            frames = ms * 16
            block = blocks[kind]
            data = array("h")
            while len(data) < frames:
                data.extend(block)
            out.writeframes(data[:frames].tobytes())
            if kind == "tone":
                tones.append((cursor, cursor + ms))
            cursor += ms
    return tones


def bursts(count: int, tone_ms: int, silence_ms: int) -> list[tuple[str, int]]:
    return [part for _ in range(count) for part in (("tone", tone_ms), ("silence", silence_ms))]


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels:format=duration,format_name",
         "-of", "json", str(path)], check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    return {"codec": data["streams"][0]["codec_name"], "channels": data["streams"][0]["channels"],
            "format": data["format"]["format_name"], "ms": float(data["format"]["duration"]) * 1000}


def residual(workdir: Path) -> list[Path]:
    return sorted(workdir.iterdir())


def vad_of(intervals: list[tuple[int, int]]) -> Any:
    calls: list[int] = []

    def run(wav: Path, audio_ms: int) -> list[tuple[int, int]]:
        calls.append(audio_ms)
        return intervals

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.fixture(scope="module")
def burst_wav(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[tuple[int, int]]]:
    # 30 bursts of 8 s tone + 2 s silence = 300 s.
    path = tmp_path_factory.mktemp("burst") / "bursts.wav"
    return path, write_wav(path, bursts(30, 8000, 2000))


# ---------------------------------------------------------------- planning (no external binaries)

def test_no_split_when_audio_fits(burst_wav: tuple[Path, list[tuple[int, int]]]) -> None:
    wav, _ = burst_wav
    assert plan_parts(wav, 300_000, 400_000, []) == ([(0, 300_000)], 0)


def test_split_at_pauses_tiles_the_timeline(burst_wav: tuple[Path, list[tuple[int, int]]]) -> None:
    wav, tones = burst_wav
    parts, dropped = plan_parts(wav, 300_000, 60_000, tones)
    assert dropped == 0
    assert parts[0][0] == 0 and parts[-1][1] == 300_000
    assert all(a[1] == b[0] for a, b in zip(parts, parts[1:], strict=False))
    assert all(high - low <= 60_000 for low, high in parts)
    # Every cut falls in a silence (never inside a tone burst).
    for _, cut in parts[:-1]:
        assert not any(start < cut < end for start, end in tones)
    assert len(parts) >= 5


def test_long_silence_is_dropped_not_uploaded(tmp_path: Path) -> None:
    wav = tmp_path / "gap.wav"
    tones = write_wav(wav, [("tone", 20_000), ("silence", 100_000), ("tone", 20_000)])
    parts, dropped = plan_parts(wav, 140_000, 30_000, tones)
    assert len(parts) == 2
    assert dropped > 0
    assert sum(high - low for low, high in parts) + dropped == 140_000
    assert parts[0][0] <= 0 + 5_000 and parts[0][1] >= 20_000
    assert parts[1][0] <= 120_000 and parts[1][1] == 140_000


def test_hard_cut_at_quietest_point_of_a_continuous_block(tmp_path: Path) -> None:
    wav = tmp_path / "continuous.wav"
    # 50 s of tone with a 200 ms quiet dip at 24 s: the quietest point of the cut window for a 30 s limit.
    tones = write_wav(wav, [("tone", 24_000), ("quiet", 200), ("tone", 25_800)])
    parts, dropped = plan_parts(wav, 50_000, 30_000, [(0, 50_000)])
    assert len(parts) == 2 and dropped == 0
    assert 24_000 <= parts[0][1] <= 24_200
    assert parts[0][1] == parts[1][0]
    assert tones  # the dip splits the tone into two intervals; VAD said one block


def test_without_vad_whole_file_is_one_block_and_hard_cut(burst_wav: tuple[Path, list[tuple[int, int]]]) -> None:
    wav, tones = burst_wav
    parts, dropped = plan_parts(wav, 300_000, 60_000, [])
    assert dropped == 0 and all(high - low <= 60_000 for low, high in parts)
    # Hard cuts still prefer the quietest frame: that is a silence of the bursts.
    for _, cut in parts[:-1]:
        assert not any(start < cut < end for start, end in tones)


def test_invalid_intervals_are_prep_errors(burst_wav: tuple[Path, list[tuple[int, int]]]) -> None:
    wav, _ = burst_wav
    with pytest.raises(AudioPrepError):
        plan_parts(wav, 300_000, 60_000, [(0, 400_000)])


@pytest.fixture(scope="module")
def short_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("short") / "short.wav"
    write_wav(path, bursts(12, 6500, 2300))  # 105.6 s
    return path


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    raw=st.lists(st.tuples(st.integers(0, 105_000), st.integers(1, 40_000)), max_size=12),
    limit=st.integers(10_000, 120_000),
)
def test_plan_properties(short_wav: Path, raw: list[tuple[int, int]], limit: int) -> None:
    audio_ms = 105_600
    intervals: list[tuple[int, int]] = []
    cursor = 0
    for start, length in sorted(raw):
        start = max(start, cursor)
        end = min(start + length, audio_ms)
        if end > start:
            intervals.append((start, end))
            cursor = end
    parts, dropped = plan_parts(short_wav, audio_ms, limit, intervals)
    assert all(0 <= low < high <= audio_ms and high - low <= limit for low, high in parts)
    assert all(a[1] <= b[0] for a, b in zip(parts, parts[1:], strict=False))
    assert sum(high - low for low, high in parts) + dropped == audio_ms


def test_vad_cli_runner_parses_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(
            command, 0, "Detected 1 speech segments:\nSpeech segment 0: start = 1.50, end = 3.00\n", ""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = vad_cli_runner(Path("/bin/vad"), Path("/m/vad.bin"), 0.5)
    assert run(tmp_path / "a.wav", 10_000) == [(15, 30)]  # whisper VAD prints centiseconds
    assert seen[0] == ["/bin/vad", "-f", str(tmp_path / "a.wav"), "-vm", "/m/vad.bin", "-vt", "0.5"]

    def broken(command: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(AudioPrepError):
        run(tmp_path / "a.wav", 10_000)


# ---------------------------------------------------------------- limits and cleanup (no ffmpeg needed)

def test_unusable_limits_raise_audio_too_large_and_leave_nothing(
    burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, _ = burst_wav
    for seconds, size in ((5, None), (None, 5_000)):
        with pytest.raises(ProviderError) as info, prepare_audio(
            wav, workdir=tmp_path, max_seconds=seconds, max_bytes=size
        ):
            pytest.fail("must not yield")
        assert info.value.code == "audio_too_large" and not info.value.retryable
        assert info.value.reason == "limit_too_small"
    assert residual(tmp_path) == []


def test_non_normalized_input_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "stereo.wav"
    with wave.open(str(bad), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(44100)
        out.writeframes(b"\0" * 4000)
    with pytest.raises(AudioPrepError), prepare_audio(bad, workdir=tmp_path):
        pytest.fail("must not yield")
    assert [p.name for p in tmp_path.iterdir()] == ["stereo.wav"]


def test_encoder_failure_and_oversize_part_clean_up(
    monkeypatch: pytest.MonkeyPatch, burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, tones = burst_wav
    work = tmp_path / "work"
    work.mkdir()

    def failing(command: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(AudioPrepError), prepare_audio(wav, workdir=work):
        pytest.fail("must not yield")
    assert residual(work) == []

    def oversize(wav_: Path, target: Path, interval: tuple[int, int], bitrate: int, timeout: float) -> None:
        target.write_bytes(b"x" * 100_001)

    monkeypatch.setattr(audio_prep, "_encode", oversize)
    with pytest.raises(ProviderError) as info, prepare_audio(wav, max_bytes=100_000, workdir=work, vad=vad_of(tones)):
        pytest.fail("must not yield")
    assert info.value.code == "audio_too_large" and info.value.reason == "part_over_limit"
    assert residual(work) == []


# ---------------------------------------------------------------- real ffmpeg

@needs_ffmpeg
def test_single_part_is_opus_mono_with_same_duration(
    burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, _ = burst_wav
    original = wav.read_bytes()
    vad = vad_of([])
    with prepare_audio(wav, vad=vad, workdir=tmp_path) as prepared:
        assert len(prepared.parts) == 1 and prepared.dropped_ms == 0
        part = prepared.parts[0]
        info = probe(part.path)
        assert (info["codec"], info["channels"], info["format"]) == ("opus", 1, "ogg")
        assert abs(info["ms"] - 300_000) <= 100 and part.offset_ms == 0
        assert part.size_bytes == part.path.stat().st_size
        # 24 kbps constrained VBR: about 3 kB per second, far below the 115 MB/h of PCM.
        assert part.size_bytes < 300 * 3000 * 1.1
        assert prepared.media_type == "audio/ogg"
    assert vad.calls == []  # no limit, no VAD run
    assert residual(tmp_path) == []
    assert wav.read_bytes() == original


@needs_ffmpeg
def test_split_by_seconds_offsets_durations_and_cleanup(
    burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, tones = burst_wav
    vad = vad_of(tones)
    with prepare_audio(wav, max_seconds=60, vad=vad, workdir=tmp_path) as prepared:
        assert vad.calls == [300_000]
        parts = prepared.parts
        assert len(parts) >= 5
        assert abs(sum(p.duration_ms for p in parts) + prepared.dropped_ms - 300_000) <= 100
        assert sum(abs(probe(p.path)["ms"] - p.duration_ms) for p in parts) <= 100 * len(parts)
        decoded = sum(probe(p.path)["ms"] for p in parts)
        assert abs(decoded - 300_000) <= 100 * len(parts)
        cursor = 0
        for p in parts:
            assert p.offset_ms == cursor and p.duration_ms <= 60_000 and p.path.exists()
            cursor += p.duration_ms
        for p in parts[1:]:
            assert not any(start < p.offset_ms < end for start, end in tones)
    assert residual(tmp_path) == []


@needs_ffmpeg
def test_split_by_bytes_keeps_each_part_under_the_limit(
    burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, tones = burst_wav
    # 100 kB at 24 kbps is about 33 s; with the 10% margin parts are planned at 30 s.
    with prepare_audio(wav, max_bytes=100_000, vad=vad_of(tones), workdir=tmp_path) as prepared:
        assert len(prepared.parts) >= 10
        assert all(p.size_bytes <= 100_000 and p.duration_ms <= 30_000 for p in prepared.parts)
        assert abs(sum(p.duration_ms for p in prepared.parts) - 300_000) <= 100
    assert residual(tmp_path) == []


@needs_ffmpeg
def test_continuous_speech_block_uses_hard_cut_with_correct_offsets(tmp_path: Path) -> None:
    wav = tmp_path / "continuous.wav"
    write_wav(wav, [("tone", 24_000), ("quiet", 200), ("tone", 25_800)])
    work = tmp_path / "work"
    work.mkdir()
    with prepare_audio(wav, max_seconds=30, vad=vad_of([(0, 50_000)]), workdir=work) as prepared:
        first, second = prepared.parts
        assert first.offset_ms == 0 and 24_000 <= second.offset_ms <= 24_200
        assert first.duration_ms + second.duration_ms == 50_000
        assert abs(probe(second.path)["ms"] - second.duration_ms) <= 100
    assert residual(work) == []


@needs_ffmpeg
def test_exception_in_caller_block_still_cleans_up(
    burst_wav: tuple[Path, list[tuple[int, int]]], tmp_path: Path
) -> None:
    wav, tones = burst_wav
    seen: list[Path] = []
    with pytest.raises(RuntimeError, match="boom"), prepare_audio(wav, max_seconds=100, vad=vad_of(tones),
                                                                  workdir=tmp_path) as prepared:
        seen = [p.path for p in prepared.parts]
        assert all(path.exists() for path in seen)
        raise RuntimeError("boom")
    assert seen and not any(path.exists() for path in seen)
    assert residual(tmp_path) == []


@needs_ffmpeg
def test_sixty_minutes_compress_under_25_mb(tmp_path: Path) -> None:
    """60 min of synthetic noise+tone bursts (7 s on, 3 s off) at 24 kbps.

    Measured on the development Mac (ffmpeg 8, libopus, 24 kbps constrained VBR, voip profile):
    - this signal: 8.20 MB (PCM source: 115.2 MB);
    - worst case, 60 min of continuous white noise with no silence: 11.23 MB at 24 kbps and
      6.46 MB at 16 kbps, i.e. about 1% above bitrate * duration.
    """
    wav = tmp_path / "hour.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:r=16000:d=3600",
         "-f", "lavfi", "-i", "anoisesrc=r=16000:a=0.3:d=3600:c=white", "-filter_complex",
         "[0][1]amix=inputs=2:normalize=0,volume=enable='gte(mod(t,10),7)':volume=0",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True,
    )
    work = tmp_path / "work"
    work.mkdir()
    with prepare_audio(wav, workdir=work) as prepared:
        (part,) = prepared.parts
        assert abs(prepared.source_ms - 3_600_000) <= 100
        assert part.size_bytes < 25 * 1024 * 1024
        assert part.size_bytes < 12 * 1024 * 1024  # bitrate * duration + ~1% container overhead, with slack
        assert abs(probe(part.path)["ms"] - 3_600_000) <= 100
    assert residual(work) == []
