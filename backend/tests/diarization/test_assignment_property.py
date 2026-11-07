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
def test_property_9_only_positive_maximum_overlap_is_assigned(
    turns: list[Turn],
    segments: list[SpeakerSegment],
) -> None:
    """Assignments exist only for turns with positive maximum overlap and report it."""
    speakers = _create_speakers(segments)
    assume(len(speakers) >= 1)
    turns = [
        *turns,
        Turn(
            id="zero-overlap",
            start_ms=100_001,
            end_ms=100_002,
            sequence=max(turn.sequence for turn in turns) + 1,
        ),
    ]

    result = assign_turns(turns, segments, speakers)
    expected: dict[str, tuple[Speaker, int]] = {}

    for turn in turns:
        overlaps = {
            speaker.raw_label: sum(
                _calculate_overlap(turn, segment)
                for segment in segments
                if segment.raw_label == speaker.raw_label
            )
            for speaker in speakers
        }
        max_overlap = max(overlaps.values())
        if max_overlap > 0:
            winning_speakers = [
                speaker
                for speaker in speakers
                if overlaps[speaker.raw_label] == max_overlap
            ]
            expected[turn.id] = (
                min(winning_speakers, key=lambda speaker: speaker.sequence),
                max_overlap,
            )

    assert [turn_id for turn_id, *_ in result] == list(expected), (
        "Only turns with positive maximum overlap may be assigned"
    )
    for assignment in result:
        assert len(assignment) == 3, "Assignments must include measured overlap_ms"
        turn_id, speaker, overlap_ms = assignment
        expected_speaker, expected_overlap = expected[turn_id]
        assert speaker == expected_speaker
        assert overlap_ms == expected_overlap


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
    assert all(len(assignment) == 3 for assignment in result), (
        "Assignments must include measured overlap_ms"
    )
    assignments_by_turn = {
        assignment[0]: (assignment[1], assignment[2]) for assignment in result
    }

    for turn in turns:
        overlaps = {
            speaker.raw_label: sum(
                _calculate_overlap(turn, segment)
                for segment in segments
                if segment.raw_label == speaker.raw_label
            )
            for speaker in speakers
        }
        max_overlap = max(overlaps.values())

        if max_overlap == 0:
            assert turn.id not in assignments_by_turn, (
                f"Turn {turn.id} has no positive overlap but was assigned"
            )
            continue

        assigned_speaker, reported_overlap = assignments_by_turn[turn.id]
        assert overlaps[assigned_speaker.raw_label] == max_overlap
        assert reported_overlap == max_overlap


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
    assert all(len(assignment) == 3 for assignment in result), (
        "Assignments must include measured overlap_ms"
    )
    assignments_by_turn = {assignment[0]: assignment[1] for assignment in result}

    for turn in turns:
        overlaps = {
            speaker.raw_label: sum(
                _calculate_overlap(turn, segment)
                for segment in segments
                if segment.raw_label == speaker.raw_label
            )
            for speaker in speakers
        }
        max_overlap = max(overlaps.values())
        if max_overlap == 0:
            assert turn.id not in assignments_by_turn
            continue

        candidates = [
            speaker for speaker in speakers
            if overlaps[speaker.raw_label] == max_overlap
        ]
        if len(candidates) > 1:
            lowest_sequence = min(candidate.sequence for candidate in candidates)
            assert assignments_by_turn[turn.id].sequence == lowest_sequence


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
