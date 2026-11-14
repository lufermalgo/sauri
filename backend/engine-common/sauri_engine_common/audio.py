"""Normalize audio without changing its playback clock."""

from __future__ import annotations

import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NormalizeReport:
    audio_ms: int
    seconds: float  # Wall time spent normalizing, not audio duration.


class NormalizeError(RuntimeError):
    """Categorized, content-free failure safe to return to engine clients."""

    code = "normalize_failed"


def normalize_to_wav(source: Path, dest: Path, *, timeout_s: float = 300) -> NormalizeReport:
    if source.resolve() == dest.resolve():
        raise NormalizeError("normalize_failed")
    started = time.monotonic()
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
            check=True, capture_output=True, timeout=timeout_s,
        )
        with wave.open(str(dest), "rb") as wav:
            audio_ms = round(wav.getnframes() * 1000 / wav.getframerate())
    except (OSError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
        dest.unlink(missing_ok=True)
        raise NormalizeError("normalize_failed") from exc
    return NormalizeReport(audio_ms=audio_ms, seconds=time.monotonic() - started)
