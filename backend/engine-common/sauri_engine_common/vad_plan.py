"""Pure VAD output parsing and silence-bounded chunk planning (no audio, no subprocess).

Shared by the native ASR engine (``asr_vad`` re-exports these names) and by external-provider
audio preparation, so both split audio at the same voice pauses.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

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
