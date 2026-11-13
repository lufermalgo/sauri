"""Turn assigner — pure assignment function by maximum temporal overlap.

Assigns each SpeechTurn to the Speaker with the maximum accumulated
temporal overlap, with deterministic tie-breaking by lowest sequence.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import Speaker


class _OverlapIndex:
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


def assign_turns(
    turns: list[Any],
    segments: list[SpeakerSegment],
    speakers: list[Speaker],
    *,
    require_exclusive: bool = False,
) -> list[tuple[str, Speaker, int]]:
    """Assigns each turn to the speaker with maximum accumulated overlap.

    Algorithm (Req. 7.1, 7.2):
    For each turn [ts, te]:
    1. For each speaker, sum the overlap with all of their segments.
       Overlap = max(0, min(te, se) - max(ts, ss))
    2. Select the speaker with the maximum accumulated overlap, only when it
       is strictly positive.
    3. Tie-break positive maxima by the lowest speaker sequence.

    With require_exclusive=True, a turn with more than one positive speaker
    candidate is deliberately unassigned; duplicated same-speaker detections
    count as a union. This mode is opt-in and does not reinterpret legacy rows.
    Turns are not modified (Req. 7.3).
    If there are no turns, segments, or speakers -> zero assignments (Req. 7.4, 7.5).

    Args:
        turns: List of objects with .id, .start_ms, .end_ms.
        segments: List of SpeakerSegment from the engine.
        speakers: List of Speaker from the labeler.

    Returns:
        List of tuples (turn_id, assigned_speaker, overlap_ms) for turns with
        positive overlap; turns with no overlap evidence are left unassigned.
    """
    if not turns or not speakers:
        return []

    # Pre-group segments by raw label for efficiency
    segments_by_label: dict[str, list[SpeakerSegment]] = {}
    for seg in segments:
        segments_by_label.setdefault(seg.raw_label, []).append(seg)

    # Build once per label, including duplicate/overlapping detections. Total
    # construction O(S log S), then O(T * H * log S) instead of O(T * S).
    indices = {
        label: _OverlapIndex(label_segments, exclusive=require_exclusive)
        for label, label_segments in segments_by_label.items()
    }
    assignments: list[tuple[str, Speaker, int]] = []

    for turn in turns:
        ts = turn.start_ms
        te = turn.end_ms

        best_speaker: Speaker | None = None
        best_overlap: int = -1
        positive_candidates = 0

        for speaker in speakers:
            index = indices.get(speaker.raw_label)
            accumulated_overlap = index.overlap(ts, te) if index is not None else 0
            if accumulated_overlap > 0:
                positive_candidates += 1

            # Select if greater overlap, or a tie with lower sequence
            if (
                accumulated_overlap > best_overlap
                or (
                    accumulated_overlap == best_overlap
                    and (
                        best_speaker is None
                        or speaker.sequence < best_speaker.sequence
                    )
                )
            ):
                best_overlap = accumulated_overlap
                best_speaker = speaker

        assert best_speaker is not None  # Guaranteed if speakers isn't empty
        if best_overlap > 0 and (not require_exclusive or positive_candidates == 1):
            assignments.append((turn.id, best_speaker, best_overlap))

    return assignments
