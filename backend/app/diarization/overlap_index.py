"""Shared temporal overlap index over speaker segments."""

from __future__ import annotations

from bisect import bisect_right

from app.diarization.diarization_engine import SpeakerSegment


class OverlapIndex:
    """Integral of interval coverage; integer area preserves exact milliseconds.

    Coverage counts every detection in accumulated mode and is capped at one
    in exclusive mode (the union). Queries do not depend on input turn order.
    """

    def __init__(self, segments: list[SpeakerSegment], *, exclusive: bool) -> None:
        events: dict[int, int] = {}
        for segment in segments:
            if segment.start_ms < segment.end_ms:
                events[segment.start_ms] = events.get(segment.start_ms, 0) + 1
                events[segment.end_ms] = events.get(segment.end_ms, 0) - 1
        self._bounds = sorted(events)
        self._areas: list[int] = []
        self._coverage: list[int] = []
        area = depth = coverage = 0
        previous = self._bounds[0] if self._bounds else 0
        for boundary in self._bounds:
            area += (boundary - previous) * coverage
            depth += events[boundary]
            coverage = min(depth, 1) if exclusive else depth
            self._areas.append(area)
            self._coverage.append(coverage)
            previous = boundary

    def _area_at(self, time_ms: int) -> int:
        position = bisect_right(self._bounds, time_ms) - 1
        if position < 0:
            return 0
        return self._areas[position] + (time_ms - self._bounds[position]) * self._coverage[position]

    def overlap(self, start_ms: int, end_ms: int) -> int:
        if start_ms >= end_ms:
            return 0
        return self._area_at(end_ms) - self._area_at(start_ms)
