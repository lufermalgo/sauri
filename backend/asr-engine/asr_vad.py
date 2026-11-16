"""External VAD parsing, silence-bounded chunks and original-clock alignment."""

from __future__ import annotations

import wave
from dataclasses import replace
from pathlib import Path

from asr_config import remaining
from sauri_engine_common.vad_plan import Interval, group_chunks, parse_vad
from whisper_words import Segment, Word, WordsResult

__all__ = ["Interval", "align_chunks", "cut_wav", "group_chunks", "parse_vad"]


def cut_wav(source: Path, target: Path, interval: Interval, deadline: float) -> None:
    with wave.open(str(source), "rb") as audio:
        format_ = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype())
        if format_ != (1, 2, 16000, "NONE"):
            raise ValueError("Expected normalized PCM16 mono 16 kHz audio")
        start, end = interval
        # normalize_to_wav rounds duration to ms; the last frame may precede
        # that boundary by less than half a millisecond. Never pad with samples.
        frames = min(end * 16, audio.getnframes()) - start * 16
        if start < 0 or frames <= 0 or end > round(audio.getnframes() / 16):
            raise ValueError("Invalid audio cut")
        audio.setpos(start * 16)
        with wave.open(str(target), "wb") as output:
            output.setparams(audio.getparams())
            while frames:
                remaining(deadline)
                count = min(frames, 16000 * 10)
                data = audio.readframes(count)
                if len(data) != count * 2:
                    raise ValueError("Incomplete normalized audio")
                output.writeframesraw(data)
                frames -= count


def align_chunks(results: list[tuple[Interval, WordsResult]]) -> WordsResult:
    """Translate once and clip backwards at observed starts; never extrapolate."""
    segments: list[Segment] = []
    inverted = 0
    for index, ((start, end), result) in enumerate(results):
        if index + 1 < len(results):
            end = min(end, results[index + 1][0][0])
        inverted += result.inverted_words
        for segment in result.segments:
            words = tuple(replace(
                word, start_ms=min(end, start + word.start_ms), end_ms=min(end, start + word.end_ms),
                timing_repaired=word.timing_repaired or start + word.end_ms > end,
            ) for word in segment.words)
            segments.append(replace(segment, start_ms=min(end, start + segment.start_ms),
                                    end_ms=min(end, start + segment.end_ms), words=words))
    # Decoder intervals can overlap even within one chunk. Clip, do not shift
    # later words forwards or synthesize durations; zero-length repairs are explicit.
    word_limit: int | None = None
    segment_limit: int | None = None
    repaired_segments: list[Segment] = []
    for segment in reversed(segments):
        repaired_words: list[Word] = []
        for word in reversed(segment.words):
            end = word.end_ms if word_limit is None else min(word.end_ms, word_limit)
            start = min(word.start_ms, end)
            repaired_words.append(replace(word, start_ms=start, end_ms=end,
                                          timing_repaired=word.timing_repaired or (start, end) !=
                                          (word.start_ms, word.end_ms)))
            word_limit = start
        end = segment.end_ms if segment_limit is None else min(segment.end_ms, segment_limit)
        start = min(segment.start_ms, end)
        repaired_segments.append(replace(segment, start_ms=start, end_ms=end, words=tuple(reversed(repaired_words))))
        segment_limit = start
    return WordsResult(tuple(reversed(repaired_segments)), inverted)
