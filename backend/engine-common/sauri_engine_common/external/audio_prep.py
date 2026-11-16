"""Prepare a normalized WAV for an external transcription or diarization provider.

Pipeline (the caller runs ``normalize_to_wav`` first; this module never touches the original):

1. Compress to Opus mono in an Ogg container (``audio/ogg``): 24 kbps constrained VBR with the
   ``voip`` application profile, which is tuned for speech. Constrained VBR keeps the size close to
   ``bitrate * duration`` (about 10.8 MB per hour plus roughly 1% Ogg overhead), so sizes can be
   planned from durations. The 16 kHz PCM source weighs about 115 MB per hour.
2. If a provider limit (``max_bytes`` and/or ``max_seconds``) is below what one file needs, split the
   audio into parts at voice pauses using the same VAD planning as the local engine
   (``vad_plan.group_chunks``) and encode each part from the WAV, so there is no generation loss.
3. Report each part with its ``offset_ms`` on the original clock, so callers add it to every
   provider timestamp.

Splitting rule
    * The per-part limit is ``min(max_seconds, 0.9 * max_bytes / bitrate)``; the 10% margin absorbs
      container overhead and VBR variation. A limit below ``MIN_PART_MS`` (10 s) is unusable.
    * Speech is planned with ``group_chunks`` against the limit minus 4 s, neighbouring chunks are
      joined back while they fit, and parts tile the timeline at the midpoint of the silence between
      chunks (the 4 s of room absorbs any pause up to the 4 s VAD inner-silence rule). Longer silence
      beyond what a part can absorb is dropped instead of uploaded (some providers fail on silent audio);
      ``dropped_ms`` reports it, so ``sum(part durations) + dropped_ms == source duration``.
    * Hard-cut fallback: a speech block longer than the limit cannot be cut at a pause. It is cut at
      the quietest 20 ms frame within the last quarter (at most 10 s) of the allowed length. This may
      split a word; it is the only case where speech is cut.
    * ``audio_too_large`` is raised only when the limit is unusable (below ``MIN_PART_MS``) or an
      encoded part still exceeds ``max_bytes``. Without a VAD callable the whole file is treated as
      one speech block, so the split is by hard cuts only.

Measured sizes (ffmpeg 8 libopus, 60 min of synthetic tone/noise bursts, 24 kbps constrained VBR):
see ``tests/engine_common/test_audio_prep.py::test_sixty_minutes_compress_under_25_mb``.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from array import array
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.vad_plan import Interval, group_chunks, parse_vad

DEFAULT_BITRATE_BPS: Final = 24_000
MEDIA_TYPE: Final = "audio/ogg"
MIN_PART_MS: Final = 10_000
SIZE_MARGIN: Final = 0.9
_FRAME_MS: Final = 20
_MAX_CUT_WINDOW_MS: Final = 10_000
_SILENCE_ROOM_MS: Final = 4_000
_MAX_INNER_SILENCE_MS: Final = 4_000  # Same threshold as vad_plan.group_chunks.
_PCM_FORMAT: Final = (1, 2, 16000, "NONE")

VadFn = Callable[[Path, int], list[Interval]]
"""Maps ``(normalized_wav, audio_ms)`` to speech intervals in ms."""


class AudioPrepError(RuntimeError):
    """Content-free failure of the preparation itself (bad WAV, ffmpeg or VAD failure)."""

    code = "audio_prep_failed"


@dataclass(frozen=True)
class AudioPart:
    path: Path
    offset_ms: int  # Start of this part on the original clock.
    duration_ms: int
    size_bytes: int


@dataclass(frozen=True)
class PreparedAudio:
    parts: tuple[AudioPart, ...]
    source_ms: int
    dropped_ms: int  # Silence not uploaded; sum(part.duration_ms) + dropped_ms == source_ms.
    bitrate_bps: int
    media_type: str = MEDIA_TYPE


def vad_cli_runner(cli: Path, model: Path, threshold: float, *, timeout_s: float = 300) -> VadFn:
    """Build a ``VadFn`` around the whisper.cpp VAD command line used by the local ASR engine."""

    def run(wav: Path, audio_ms: int) -> list[Interval]:
        try:
            process = subprocess.run(
                [str(cli), "-f", str(wav), "-vm", str(model), "-vt", str(threshold)],
                check=True, capture_output=True, text=True, timeout=timeout_s,
            )
            return parse_vad(process.stdout, audio_ms)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise AudioPrepError("audio_prep_failed") from exc

    return run


def _wav_ms(wav: Path) -> int:
    try:
        with wave.open(str(wav), "rb") as audio:
            format_ = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype())
            if format_ != _PCM_FORMAT:
                raise AudioPrepError("audio_prep_failed")
            return round(audio.getnframes() * 1000 / audio.getframerate())
    except (OSError, wave.Error, EOFError) as exc:
        raise AudioPrepError("audio_prep_failed") from exc


def _part_limit_ms(max_bytes: int | None, max_seconds: float | None, bitrate_bps: int) -> int | None:
    limits: list[int] = []
    if max_seconds is not None:
        limits.append(int(max_seconds * 1000))
    if max_bytes is not None:
        limits.append(int(max_bytes * 8 * 1000 * SIZE_MARGIN / bitrate_bps))
    if not limits:
        return None
    limit = min(limits)
    if limit < MIN_PART_MS:
        raise ProviderError("audio_too_large", reason="limit_too_small")
    return limit


def _quietest_cut_ms(wav: Path, low_ms: int, high_ms: int) -> int:
    """Middle of the lowest-energy 20 ms frame in ``[low_ms, high_ms)``."""
    with wave.open(str(wav), "rb") as audio:
        audio.setpos(low_ms * 16)
        samples = array("h")
        samples.frombytes(audio.readframes((high_ms - low_ms) * 16))
    if sys.byteorder == "big":
        samples.byteswap()
    size = _FRAME_MS * 16
    energies = [sum(x * x for x in samples[i:i + size]) for i in range(0, len(samples) - size + 1, size)]
    if not energies:
        raise AudioPrepError("audio_prep_failed")
    return low_ms + energies.index(min(energies)) * _FRAME_MS + _FRAME_MS // 2


def _hard_cut(wav: Path, start: int, end: int, limit_ms: int) -> list[Interval]:
    pieces: list[Interval] = []
    cursor = start
    window = min(limit_ms // 4, _MAX_CUT_WINDOW_MS)
    while end - cursor > limit_ms:
        cut = _quietest_cut_ms(wav, cursor + limit_ms - window, cursor + limit_ms)
        pieces.append((cursor, cut))
        cursor = cut
    pieces.append((cursor, end))
    return pieces


def plan_parts(wav: Path, audio_ms: int, limit_ms: int, intervals: list[Interval]) -> tuple[list[Interval], int]:
    """Return parts (each at most ``limit_ms``, in order) and the dropped silence in ms."""
    if audio_ms <= limit_ms:
        return [(0, audio_ms)], 0
    # Speech is planned against a smaller cap so every part keeps room to absorb the silences on both
    # sides (VAD pauses inside a group are at most 4 s), which makes the parts tile the timeline.
    cap = limit_ms - _SILENCE_ROOM_MS
    try:
        chunks = group_chunks(intervals or [(0, audio_ms)], audio_ms, cap)
    except ValueError as exc:
        raise AudioPrepError("audio_prep_failed") from exc
    pieces: list[Interval] = []
    for start, end in chunks:
        pieces.extend(_hard_cut(wav, start, end, cap) if end - start > cap else [(start, end)])
    packed: list[Interval] = []
    for start, end in pieces:
        # group_chunks splits at the largest gap until it fits; join neighbours back while they still fit.
        if packed and start - packed[-1][1] <= _MAX_INNER_SILENCE_MS and end - packed[-1][0] <= cap:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    parts: list[Interval] = []
    dropped = 0
    cursor = 0  # End of the previous part.
    for index, (start, end) in enumerate(packed):
        before = 0 if index == 0 else (packed[index - 1][1] + start) // 2
        after = audio_ms if index == len(packed) - 1 else (end + packed[index + 1][0]) // 2
        slack = (limit_ms - (end - start)) // 2
        low, high = max(before, start - slack), min(after, end + slack)
        dropped += low - cursor
        parts.append((low, high))
        cursor = high
    return parts, dropped + audio_ms - cursor


def _encode(wav: Path, target: Path, interval: Interval, bitrate_bps: int, timeout_s: float) -> None:
    start, end = interval
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start / 1000:.3f}",
             "-t", f"{(end - start) / 1000:.3f}", "-i", str(wav),
             "-vn", "-ac", "1", "-c:a", "libopus", "-b:a", str(bitrate_bps), "-vbr", "constrained",
             "-application", "voip", "-f", "ogg", str(target)],
            check=True, capture_output=True, timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioPrepError("audio_prep_failed") from exc


@contextmanager
def prepare_audio(
    wav: Path,
    *,
    max_bytes: int | None = None,
    max_seconds: float | None = None,
    vad: VadFn | None = None,
    bitrate_bps: int = DEFAULT_BITRATE_BPS,
    workdir: Path | None = None,
    timeout_s: float = 300,
) -> Iterator[PreparedAudio]:
    """Yield the compressed parts; every temporary file is removed when the block exits, even on error.

    ``wav`` must be the output of ``normalize_to_wav`` (PCM16, mono, 16 kHz) and is never modified.
    ``vad`` is only called when a split is needed.
    """
    audio_ms = _wav_ms(wav)
    if audio_ms <= 0:
        raise AudioPrepError("audio_prep_failed")
    limit_ms = _part_limit_ms(max_bytes, max_seconds, bitrate_bps)
    with tempfile.TemporaryDirectory(prefix="sauri-audio-prep-", dir=workdir) as temporary:
        split = limit_ms is not None and audio_ms > limit_ms
        intervals = vad(wav, audio_ms) if split and vad is not None else []
        planned, dropped = plan_parts(wav, audio_ms, limit_ms if limit_ms is not None else audio_ms, intervals)
        parts: list[AudioPart] = []
        for index, interval in enumerate(planned):
            target = Path(temporary) / f"part-{index:04d}.ogg"
            _encode(wav, target, interval, bitrate_bps, timeout_s)
            size = target.stat().st_size
            if max_bytes is not None and size > max_bytes:
                raise ProviderError("audio_too_large", reason="part_over_limit")
            parts.append(AudioPart(target, interval[0], interval[1] - interval[0], size))
        yield PreparedAudio(tuple(parts), audio_ms, dropped, bitrate_bps)
