"""Property test for turn assignment by maximum temporal overlap.

# Feature: speaker-identification, Property 9: Turn assignment by maximum overlap with deterministic tie-break
Validates: Requirements 7.1, 7.2
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import Speaker

# ---------------------------------------------------------------------------
# Helper types for turns (simplified stand-in for the ORM SpeechTurn)
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """Simplified representation of a SpeechTurn for tests."""

    id: str
    start_ms: int
    end_ms: int
    sequence: int


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------

# Possible raw labels for speakers
raw_labels_strategy = st.sampled_from(
    ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03", "SPEAKER_04"]
)


def _segment_strategy(
    label: st.SearchStrategy[str] = raw_labels_strategy,
) -> st.SearchStrategy[SpeakerSegment]:
    """Generates a valid SpeakerSegment."""
    return st.builds(
        SpeakerSegment,
        raw_label=label,
        start_ms=st.integers(min_value=0, max_value=100_000),
        end_ms=st.integers(min_value=0, max_value=100_000),
    ).filter(lambda s: s.end_ms >= s.start_ms)


segments_strategy = st.lists(
    _segment_strategy(), min_size=1, max_size=20
)

turns_strategy = st.lists(
    st.builds(
        Turn,
        id=st.uuids().map(str),
        start_ms=st.integers(min_value=0, max_value=100_000),
        end_ms=st.integers(min_value=0, max_value=100_000),
        sequence=st.integers(min_value=1, max_value=100),
    ).filter(lambda t: t.end_ms >= t.start_ms),
    min_size=1,
    max_size=10,
)


def _create_speakers(segments: list[SpeakerSegment]) -> list[Speaker]:
    """Creates a list of Speaker from the distinct raw labels.

    Assigns consecutive sequence from 1 (by order of first appearance).
    """
    labels_seen: dict[str, int] = {}
    for seg in segments:
        if seg.raw_label not in labels_seen:
            labels_seen[seg.raw_label] = len(labels_seen) + 1

    return [
        Speaker(
            raw_label=label,
            label=f"Speaker {sequence}",
            sequence=sequence,
        )
        for label, sequence in labels_seen.items()
    ]


def _calculate_overlap(turn: Turn, segment: SpeakerSegment) -> int:
    """Calculates the temporal overlap between a turn and a segment.

    Formula: max(0, min(turn.end_ms, seg.end_ms) - max(turn.start_ms, seg.start_ms))
    """
    return max(0, min(turn.end_ms, segment.end_ms) - max(turn.start_ms, segment.start_ms))


# ---------------------------------------------------------------------------
# Property 9: Turn assignment by maximum overlap with deterministic tie-break
# Feature: speaker-identification, Property 9: Turn assignment by maximum overlap with deterministic tie-break
# Validates: Requirements 7.1, 7.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    turns=turns_strategy,
    segments=segments_strategy,
)
def test_property_9_exactly_one_assignment_per_turn(
    turns: list[Turn],
    segments: list[SpeakerSegment],
) -> None:
    """The assigner produces exactly one assignment per turn."""
    speakers = _create_speakers(segments)
    assume(len(speakers) >= 1)

    result = assign_turns(turns, segments, speakers)

    assert len(result) == len(turns), (
        f"Expected {len(turns)} assignments, got {len(result)}"
    )
    # Each element is a tuple (turn_id, speaker)
    for turn_id, speaker in result:
        assert isinstance(turn_id, str)
        assert isinstance(speaker, Speaker)


@settings(max_examples=100)
@given(
    turns=turns_strategy,
    segments=segments_strategy,
)
def test_property_9_assignment_to_speaker_with_maximum_overlap(
    turns: list[Turn],
    segments: list[SpeakerSegment],
) -> None:
    """Each turn is assigned to the speaker with maximum accumulated overlap."""
    speakers = _create_speakers(segments)
    assume(len(speakers) >= 1)

    result = assign_turns(turns, segments, speakers)

    for turn, (turn_id, assigned_speaker) in zip(turns, result, strict=False):
        assert turn_id == turn.id

        # Compute accumulated overlap per speaker
        overlaps: dict[str, int] = {}
        for sp in speakers:
            accumulated_overlap = sum(
                _calculate_overlap(turn, seg)
                for seg in segments
                if seg.raw_label == sp.raw_label
            )
            overlaps[sp.raw_label] = accumulated_overlap

        # Find the maximum overlap
        max_overlap = max(overlaps.values())

        # The assigned speaker must have the maximum overlap
        assert overlaps[assigned_speaker.raw_label] == max_overlap, (
            f"Turn {turn.id}: assigned speaker '{assigned_speaker.raw_label}' "
            f"has overlap {overlaps[assigned_speaker.raw_label]} but the max is {max_overlap}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
@given(
    turns=turns_strategy,
    segments=segments_strategy,
)
def test_property_9_tie_break_by_lower_sequence(
    turns: list[Turn],
    segments: list[SpeakerSegment],
) -> None:
    """In case of an overlap tie, the speaker with the lowest sequence is assigned."""
    speakers = _create_speakers(segments)
    assume(len(speakers) >= 2)

    result = assign_turns(turns, segments, speakers)

    for turn, (_turn_id, assigned_speaker) in zip(turns, result, strict=False):
        # Compute accumulated overlap per speaker
        overlaps: dict[str, int] = {}
        for sp in speakers:
            accumulated_overlap = sum(
                _calculate_overlap(turn, seg)
                for seg in segments
                if seg.raw_label == sp.raw_label
            )
            overlaps[sp.raw_label] = accumulated_overlap

        max_overlap = max(overlaps.values())

        # Candidates with the same maximum overlap
        candidates = [
            sp for sp in speakers
            if overlaps[sp.raw_label] == max_overlap
        ]

        if len(candidates) > 1:
            # On a tie, the one with the lowest sequence must win
            lowest_sequence = min(c.sequence for c in candidates)
            assert assigned_speaker.sequence == lowest_sequence, (
                f"Turn {turn.id}: overlap tie ({max_overlap}ms) between "
                f"{[c.label for c in candidates]}, expected sequence {lowest_sequence} "
                f"but sequence {assigned_speaker.sequence} was assigned"
            )


# ---------------------------------------------------------------------------
# Property 10: Preservation of the Transcript's SpeechTurns
# Feature: speaker-identification, Property 10: Preservation of the Transcript's SpeechTurns
# Validates: Requirements 7.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    turns=turns_strategy,
    segments=segments_strategy,
)
def test_property_10_preservation_of_speech_turns(
    turns: list[Turn],
    segments: list[SpeakerSegment],
) -> None:
    """assign_turns doesn't modify text, start_ms, end_ms, or sequence of the turns."""
    speakers = _create_speakers(segments)
    assume(len(speakers) >= 1)

    # Capture original state of the turns
    turns_before = [
        (t.id, t.start_ms, t.end_ms, t.sequence) for t in turns
    ]

    assign_turns(turns, segments, speakers)

    # Verify the turns were not modified (Req. 7.3)
    turns_after = [
        (t.id, t.start_ms, t.end_ms, t.sequence) for t in turns
    ]
    assert turns_before == turns_after, (
        "assign_turns modified the input turns"
    )
