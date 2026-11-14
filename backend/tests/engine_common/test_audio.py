"""Real ffmpeg normalization of synthetic audio only."""

import subprocess
import wave
from pathlib import Path

import pytest
from sauri_engine_common.audio import NormalizeError, normalize_to_wav


def test_normalize_preserves_clock_and_original(tmp_path: Path) -> None:
    source, dest = tmp_path / "tone.wav", tmp_path / "normalized.wav"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=3", "-ac", "2", "-ar", "44100", str(source),
    ], check=True)
    original = source.read_bytes()
    report = normalize_to_wav(source, dest)
    assert abs(report.audio_ms - 3000) <= 100
    assert report.seconds > 0
    with wave.open(str(dest)) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
    assert source.read_bytes() == original


def test_corrupt_audio_is_categorized_and_partial_output_removed(tmp_path: Path) -> None:
    source, dest = tmp_path / "corrupt.webm", tmp_path / "out.wav"
    source.write_bytes(b"synthetic invalid audio")
    with pytest.raises(NormalizeError, match="normalize_failed"):
        normalize_to_wav(source, dest)
    assert not dest.exists()
    assert source.exists()


def test_refuses_to_overwrite_original(tmp_path: Path) -> None:
    source = tmp_path / "original.wav"
    source.write_bytes(b"preserve")
    with pytest.raises(NormalizeError):
        normalize_to_wav(source, source)
    assert source.read_bytes() == b"preserve"


def test_timeout_removes_partial_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dest = tmp_path / "out.wav"

    def timeout(command: list[str], **kwargs: object) -> None:
        dest.write_bytes(b"partial")
        assert kwargs["timeout"] == 1
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(NormalizeError):
        normalize_to_wav(tmp_path / "in.webm", dest, timeout_s=1)
    assert not dest.exists()
