"""Turn assigner — pure assignment function by maximum temporal overlap.

Assigns each SpeechTurn to the Speaker with the maximum accumulated
temporal overlap, with deterministic tie-breaking by lowest sequence.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from typing import Any

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import Speaker


def assign_turns(
    turns: list[Any],
    segments: list[SpeakerSegment],
    speakers: list[Speaker],
) -> list[tuple[str, Speaker]]:
    """Assigns each turn to the speaker with maximum accumulated overlap.

    Algorithm (Req. 7.1, 7.2):
    For each turn [ts, te]:
    1. For each speaker, sum the overlap with all of their segments.
       Overlap = max(0, min(te, se) - max(ts, ss))
    2. Select the speaker with the maximum accumulated overlap.
    3. Tie-break: if there's a tie (or everyone has zero overlap), assign
       to the speaker with the lowest sequence.
    4. Produce exactly one assignment per turn.

    Turns are not modified (Req. 7.3).
    If there are no turns -> zero assignments (Req. 7.4).
    If there are no segments/speakers -> zero assignments (Req. 7.5).

    Args:
        turns: List of objects with .id, .start_ms, .end_ms.
        segments: List of SpeakerSegment from the engine.
        speakers: List of Speaker from the labeler.

    Returns:
        List of tuples (turn_id, assigned_speaker), one per turn.
    """
    if not turns or not speakers:
        return []

    # Pre-group segments by raw label for efficiency
    segments_by_label: dict[str, list[SpeakerSegment]] = {}
    for seg in segments:
        segments_by_label.setdefault(seg.raw_label, []).append(seg)

    assignments: list[tuple[str, Speaker]] = []

    for turn in turns:
        ts = turn.start_ms
        te = turn.end_ms

        best_speaker: Speaker | None = None
        best_overlap: int = -1

        for speaker in speakers:
            speaker_segments = segments_by_label.get(speaker.raw_label, [])
            accumulated_overlap = sum(
                max(0, min(te, seg.end_ms) - max(ts, seg.start_ms))
                for seg in speaker_segments
            )

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
        assignments.append((turn.id, best_speaker))

    return assignments
