"""Synthetic PCM conversion contracts: full audio in RAM, never a disk WAV."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_diar_memory_audio", Path(__file__).resolve().parents[2] / "diar-engine/native_main.py"
)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)


def test_conversion_keeps_exact_pcm_in_a_seekable_memory_wav(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    original = tmp_path / "original.webm"
    original.write_bytes(b"synthetic-container")
    pcm = b"\x00\x80\xff\x7f\x00\x00\x01\x00"

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[-3:] == ["-f", "s16le", "pipe:1"]
        assert command[command.index("-ar") + 1] == "16000"
        assert command[command.index("-ac") + 1] == "1"
        assert command[command.index("-c:a") + 1] == "pcm_s16le"
        assert options == {"check": True, "capture_output": True, "timeout": native.FFMPEG_TIMEOUT_SECONDS}
        return subprocess.CompletedProcess(command, 0, stdout=pcm)

    monkeypatch.setattr(native.shutil, "which", lambda _: "/synthetic/ffmpeg")
    monkeypatch.setattr(native.subprocess, "run", run)
    with native._convert_to_wav(str(original)) as converted:
        assert isinstance(converted, io.BytesIO)
        assert converted.seekable()
        with wave.open(converted, "rb") as reader:
            assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (16000, 1, 2)
            assert reader.readframes(reader.getnframes()) == pcm
    assert converted.closed
    assert original.read_bytes() == b"synthetic-container"
    assert list(tmp_path.iterdir()) == [original]


def test_failed_conversion_preserves_source_and_creates_no_derivative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    original = tmp_path / "original.webm"
    original.write_bytes(b"synthetic-container")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("synthetic-ffmpeg", 60)

    monkeypatch.setattr(native.shutil, "which", lambda _: "/synthetic/ffmpeg")
    monkeypatch.setattr(native.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="Audio conversion failed"):
        native._convert_to_wav(str(original))
    assert original.read_bytes() == b"synthetic-container"
    assert list(tmp_path.iterdir()) == [original]
