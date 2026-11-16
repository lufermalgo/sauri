"""External VAD parsing, silence-bounded chunks and original-clock alignment."""

from __future__ import annotations

import re
import wave
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from asr_config import remaining
from whisper_words import Segment, Word, WordsResult

Interval = tuple[int, int]
_HEADER = re.compile(r"Detected ([0-9]+) speech segments:")
_SEGMENT = re.compile(r"Speech segment ([0-9]+): start = ([0-9]+(?:\.[0-9]+)?), end = ([0-9]+(?:\.[0-9]+)?)")


def parse_vad(stdout: str, audio_ms: int) -> list[Interval]:
    count: int | None = None
    intervals: list[Interval] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if match := _HEADER.fullmatch(line):
            if count is not None:
                raise ValueError("Duplicate VAD header")
            count = int(match[1])
        elif match := _SEGMENT.fullmatch(line):
            if int(match[1]) != len(intervals):
                raise ValueError("Invalid VAD segment sequence")
            # The standalone whisper VAD tool prints centiseconds, not ms.
            start, end = (int((Decimal(match[i]) * 10).to_integral_value(rounding=ROUND_HALF_UP)) for i in (2, 3))
            end = min(end, audio_ms)
            if start < 0 or end <= start or (intervals and start < intervals[-1][1]):
                raise ValueError("Invalid VAD interval")
            intervals.append((start, end))
        elif line.startswith("Speech segment ") or (line.startswith("Detected ") and "speech segments" in line):
            raise ValueError("Malformed VAD output")
    if count is None or count != len(intervals):
        raise ValueError("Incomplete VAD output")
    return intervals


def group_chunks(intervals: list[Interval], audio_ms: int, maximum_ms: int) -> list[Interval]:
    """Split at long silences, then recursively at largest gaps until bounded."""
    if maximum_ms <= 0:
        raise ValueError("Invalid chunk limit")
    groups: list[list[Interval]] = []
    for start, end in intervals:
        if not 0 <= start < end <= audio_ms or (groups and start < groups[-1][-1][1]):
            raise ValueError("Invalid speech interval")
        if not groups or start - groups[-1][-1][1] > 4000:
            groups.append([])
        groups[-1].append((start, end))
    pending = list(reversed(groups))
    chunks: list[Interval] = []
    speech_ends: list[int] = []
    while pending:
        group = pending.pop()
        start, end = max(0, group[0][0] - 300), min(audio_ms, group[-1][1] + 300)
        if end - start > maximum_ms and len(group) > 1:
            split = max(range(1, len(group)), key=lambda i: group[i][0] - group[i - 1][1])
            pending.extend([group[split:], group[:split]])
            continue
        if end - start > maximum_ms and group[-1][1] - group[0][0] <= maximum_ms:
            # A single interval fits: trim padding, never speech, to honor the limit.
            start = max(start, group[-1][1] - maximum_ms)
            end = min(end, start + maximum_ms)
        if chunks and chunks[-1][1] > start:
            # Put the shared boundary in silence; padding must not cut speech.
            start = max(start, speech_ends[-1])
            chunks[-1] = (chunks[-1][0], start)
        chunks.append((start, end))
        speech_ends.append(group[-1][1])
    return chunks


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
