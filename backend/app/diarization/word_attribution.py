"""Word-level speaker attribution and grouping of attributed words into turns.

Pure functions (design §6 of core-speech-pipeline; Requirement 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.overlap_index import OverlapIndex

MIN_WORD_DURATION_MS = 20
ZERO_LENGTH_PADDING_MS = 10
ASSIGN_PERCENT = 40
SECOND_PERCENT = 25
MARGIN_PERCENT = 20


@dataclass(frozen=True)
class WordTime:
    sequence: int
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class WordAttribution:
    word_sequence: int
    raw_label: str | None
    state: Literal["assigned", "ambiguous", "unassigned"]
    candidates: tuple[tuple[str, float], ...]  # (raw_label, overlap fraction of the word)


@dataclass(frozen=True)
class AttributedTurn:
    sequence: int
    raw_label: str | None
    start_ms: int
    end_ms: int
    text: str
    word_count: int
    has_ambiguous: bool


def attribute_words(
    words: Sequence[WordTime],
    segments: Sequence[SpeakerSegment],
    *,
    near_ms: int = 500,
) -> list[WordAttribution]:
    """Attributes each word to a raw speaker label by temporal overlap.

    With d = max(duration, 20 ms) and per-label overlap as the union of that
    label's segments: the top label is assigned when it covers >= 40 % of d,
    unless the second covers >= 25 % of d and trails by < 20 % of d (ambiguous).
    Below 40 %, the nearest segment within ``near_ms`` assigns its label;
    otherwise the word is unassigned. Ties break by smaller gap, then raw_label.
    """
    segments_by_label: dict[str, list[SpeakerSegment]] = {}
    for segment in segments:
        segments_by_label.setdefault(segment.raw_label, []).append(segment)
    indices = {
        label: OverlapIndex(label_segments, exclusive=True)
        for label, label_segments in sorted(segments_by_label.items())
    }
    timed_segments = [segment for segment in segments if segment.start_ms < segment.end_ms]

    attributions: list[WordAttribution] = []
    for word in words:
        duration = max(word.end_ms - word.start_ms, MIN_WORD_DURATION_MS)
        start, end = word.start_ms, word.end_ms
        if start == end:
            start, end = start - ZERO_LENGTH_PADDING_MS, end + ZERO_LENGTH_PADDING_MS

        overlaps = sorted(
            ((label, overlap) for label, index in indices.items() if (overlap := index.overlap(start, end)) > 0),
            key=lambda item: (-item[1], item[0]),
        )
        top = overlaps[0][1] if overlaps else 0
        if top * 100 >= ASSIGN_PERCENT * duration:
            second = overlaps[1][1] if len(overlaps) > 1 else 0
            if second * 100 >= SECOND_PERCENT * duration and (top - second) * 100 < MARGIN_PERCENT * duration:
                candidates = tuple((label, overlap / duration) for label, overlap in overlaps)
                attributions.append(WordAttribution(word.sequence, None, "ambiguous", candidates))
            else:
                attributions.append(WordAttribution(word.sequence, overlaps[0][0], "assigned", ()))
            continue

        nearest = min(
            (
                (max(0, segment.start_ms - end, start - segment.end_ms), segment.raw_label)
                for segment in timed_segments
            ),
            default=None,
        )
        if nearest is not None and nearest[0] <= near_ms:
            attributions.append(WordAttribution(word.sequence, nearest[1], "assigned", ()))
        else:
            attributions.append(WordAttribution(word.sequence, None, "unassigned", ()))
    return attributions


def group_words_into_turns(
    words: Sequence[WordTime],
    attributions: Sequence[WordAttribution],
    *,
    split_gap_ms: int = 2000,
) -> list[AttributedTurn]:
    """Groups consecutive words of the same assigned label into turns.

    Unassigned and ambiguous words continue the current turn; a turn without a
    label adopts the first assigned label it receives. A silence longer than
    ``split_gap_ms`` between consecutive words starts a new turn.
    """
    turns: list[AttributedTurn] = []
    current: list[WordTime] = []
    label: str | None = None
    has_ambiguous = False

    def close() -> None:
        turns.append(
            AttributedTurn(
                sequence=len(turns) + 1,
                raw_label=label,
                start_ms=min(word.start_ms for word in current),
                end_ms=max(word.end_ms for word in current),
                text="".join(word.text for word in current),
                word_count=len(current),
                has_ambiguous=has_ambiguous,
            )
        )

    for word, attribution in zip(words, attributions, strict=True):
        assigned = attribution.raw_label if attribution.state == "assigned" else None
        if current and (
            word.start_ms - current[-1].end_ms > split_gap_ms
            or (assigned is not None and label is not None and assigned != label)
        ):
            close()
            current, label, has_ambiguous = [], None, False
        current.append(word)
        if label is None:
            label = assigned
        has_ambiguous = has_ambiguous or attribution.state == "ambiguous"
    if current:
        close()
    return turns
