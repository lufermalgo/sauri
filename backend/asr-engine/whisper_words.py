"""Pure conversion of whisper.cpp ``-ojf`` token JSON into timed words.

Rules (design §2 of core-speech-pipeline): special tokens are skipped, sub-word
tokens are merged into the previous word, and impossible timings are repaired
deterministically. Alignment is never fabricated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SPECIAL_TOKEN_MIN_ID = 50257
_WORD_START_CHARS = (" ", "\n", "\t")


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    probability: float
    timing_repaired: bool


@dataclass(frozen=True)
class Segment:
    text: str
    start_ms: int
    end_ms: int
    words: tuple[Word, ...]


@dataclass(frozen=True)
class WordsResult:
    segments: tuple[Segment, ...]
    inverted_words: int


class NoWordTimestampsError(ValueError):
    """A segment has text but the engine reported no word-level tokens."""


@dataclass
class _RawWord:
    text: str
    start_ms: int
    end_ms: int
    probability: float


def _merge_tokens(tokens: list[Mapping[str, Any]]) -> list[_RawWord]:
    words: list[_RawWord] = []
    for token in tokens:
        if int(token["id"]) >= SPECIAL_TOKEN_MIN_ID:
            continue
        text = str(token["text"])
        offsets = token["offsets"]
        start, end = int(offsets["from"]), int(offsets["to"])
        probability = float(token["p"])
        if words and not text.startswith(_WORD_START_CHARS):
            previous = words[-1]
            previous.text += text
            previous.end_ms = max(previous.end_ms, end)
            previous.probability = min(previous.probability, probability)
        else:
            words.append(_RawWord(text, start, end, probability))
    return words


def repair_word_timing(
    start_ms: int, end_ms: int, audio_ms: int, previous_valid_end: int,
) -> tuple[int, int, bool]:
    """Repair inverted/negative timestamps, then clip to the recording duration."""
    repaired = end_ms < start_ms or start_ms < 0
    if repaired:
        start_ms = end_ms = previous_valid_end
    return min(start_ms, audio_ms), min(end_ms, audio_ms), repaired


def words_from_ggml_json(doc: Mapping[str, Any], audio_ms: int) -> WordsResult:
    segments: list[Segment] = []
    inverted_words = 0
    previous_valid_end = 0
    for raw_segment in doc.get("transcription", []):
        words: list[Word] = []
        for raw in _merge_tokens(list(raw_segment.get("tokens", []))):
            start, end, repaired = repair_word_timing(raw.start_ms, raw.end_ms, audio_ms, previous_valid_end)
            inverted_words += int(repaired)
            if not repaired:
                previous_valid_end = end
            words.append(Word(raw.text, start, end, raw.probability, repaired))
        text = str(raw_segment.get("text", ""))
        if text.strip() and not words:
            raise NoWordTimestampsError("no_word_timestamps")
        offsets = raw_segment.get("offsets", {})
        seg_start = min(max(int(offsets.get("from", 0)), 0), audio_ms)
        seg_end = min(max(int(offsets.get("to", 0)), seg_start), audio_ms)
        segments.append(Segment(text, seg_start, seg_end, tuple(words)))
    return WordsResult(tuple(segments), inverted_words)
