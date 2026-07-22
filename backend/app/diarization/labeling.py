"""Speaker labeler — pure anonymous labeling function.

Groups SpeakerSegments by raw label, orders by first appearance with
lexicographic tie-breaking, and assigns consecutive anonymous labels.

Requirements: 5.5, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

from dataclasses import dataclass

from app.diarization.diarization_engine import SpeakerSegment


@dataclass(frozen=True, slots=True)
class Speaker:
    """Anonymous speaker identified by the labeler.

    Contains no nominal identity field or personal data (Req. 6.3).

    Attributes:
        raw_label: Original raw speaker label from the engine.
        label: Speaker label formatted as "Speaker N" (Req. 6.2).
        sequence: Consecutive from 1, by first appearance (Req. 6.2).
    """

    raw_label: str
    label: str
    sequence: int


def label_speakers(segments: list[SpeakerSegment]) -> list[Speaker]:
    """Labels speakers anonymously, in order, and deterministically.

    Algorithm:
    1. Group segments by raw_label; compute the first start_ms of each
       raw label (Req. 6.1).
    2. Sort by (first_start_ms, raw_label) ascending — deterministic
       lexicographic tie-break (Req. 6.4).
    3. Assign consecutive sequence from 1 and label "Speaker N" (Req. 6.2).
    4. No nominal identity fields (Req. 6.3).

    Args:
        segments: List of SpeakerSegment produced by the engine.

    Returns:
        List of Speaker, one per distinct raw label, ordered by first
        temporal appearance.
    """
    if not segments:
        return []

    # Step 1: Compute the first start_ms per raw label
    first_start: dict[str, int] = {}
    for seg in segments:
        if seg.raw_label not in first_start:
            first_start[seg.raw_label] = seg.start_ms
        else:
            first_start[seg.raw_label] = min(
                first_start[seg.raw_label], seg.start_ms
            )

    # Step 2: Sort by (first_start_ms, raw_label) ascending
    ordered_labels = sorted(
        first_start.keys(),
        key=lambda rl: (first_start[rl], rl),
    )

    # Step 3: Assign consecutive sequence and label "Speaker N"
    speakers: list[Speaker] = []
    for i, raw_label in enumerate(ordered_labels, start=1):
        speakers.append(
            Speaker(
                raw_label=raw_label,
                label=f"Speaker {i}",
                sequence=i,
            )
        )

    return speakers
