"""Re-attribute speakers to a regenerated transcript by time overlap (#1053).

Replacing a transcript changes its turns and words, but the people who spoke and
when they spoke are unchanged. Every new span takes the speaker of the old span it
overlaps most, so the previous speaker detection stays usable (and stale) until
the speakers are explicitly regenerated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Span(Generic[T]):
    start_ms: int
    end_ms: int
    value: T


def remap_spans(old: Sequence[Span[T]], new: Sequence[tuple[int, int]], *, nearest: bool) -> list[T | None]:
    """The old value with the largest overlap for each new span, or None.

    With ``nearest`` a span that overlaps nothing takes the closest old span instead.
    """
    ordered = sorted(old, key=lambda span: (span.start_ms, span.end_ms))
    result: list[T | None] = [None] * len(new)
    if not ordered:
        return result
    first = 0
    for index in sorted(range(len(new)), key=lambda i: new[i]):
        start, end = new[index]
        while first < len(ordered) and ordered[first].end_ms <= start and ordered[first].start_ms < start:
            first += 1
        best, best_overlap = None, 0
        scan = first
        while scan < len(ordered) and ordered[scan].start_ms < max(end, start + 1):
            span = ordered[scan]
            overlap = min(end, span.end_ms) - max(start, span.start_ms)
            if overlap > best_overlap:
                best, best_overlap = span, overlap
            scan += 1
        if best is None and nearest:
            best = min(ordered, key=lambda span: max(span.start_ms - end, start - span.end_ms, 0))
        result[index] = best.value if best is not None else None
    return result
