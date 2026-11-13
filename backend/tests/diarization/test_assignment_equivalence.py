"""#907 / performance-observability-pipeline T1: differential contract oracle.

The oracle retains the pre-index scan/clip/union algorithm independently of
production helpers. No acoustic inference or source audio is needed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from runpy import run_path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import Speaker


@dataclass
class Turn:
    id: str
    start_ms: int
    end_ms: int


def reference_assignment(
    turns: list[Turn], segments: list[SpeakerSegment], speakers: list[Speaker], *, require_exclusive: bool,
) -> list[tuple[str, Speaker, int]]:
    """Pre-index semantics, deliberately using a full independent interval scan."""
    assignments = []
    for turn in turns:
        winner = None
        best_overlap = -1
        positive = 0
        for speaker in speakers:
            intersections = sorted(
                (max(turn.start_ms, segment.start_ms), min(turn.end_ms, segment.end_ms))
                for segment in segments
                if segment.raw_label == speaker.raw_label
                and min(turn.end_ms, segment.end_ms) > max(turn.start_ms, segment.start_ms)
            )
            if require_exclusive:
                overlap = 0
                previous_end = turn.start_ms
                for start, end in intersections:
                    overlap += max(0, end - max(start, previous_end))
                    previous_end = max(previous_end, end)
            else:
                overlap = sum(end - start for start, end in intersections)
            positive += overlap > 0
            if overlap > best_overlap or (
                overlap == best_overlap and (winner is None or speaker.sequence < winner.sequence)
            ):
                winner, best_overlap = speaker, overlap
        if winner is not None and best_overlap > 0 and (not require_exclusive or positive == 1):
            assignments.append((turn.id, winner, best_overlap))
    return assignments


# Small coordinate space deliberately produces ties, nesting, exact boundaries,
# duplicate detections, gaps, zero-length and inverted intervals, in arbitrary order.
coordinate = st.integers(min_value=-50, max_value=100)
interval = st.tuples(coordinate, coordinate)
segment_data = st.lists(st.tuples(st.sampled_from(["A", "B", "C", "unlisted"]), coordinate, coordinate), max_size=35)
speaker_data = st.lists(
    st.tuples(st.sampled_from(["A", "B", "C", "missing"]), st.integers(min_value=0, max_value=5)), max_size=6,
)


@settings(max_examples=400, deadline=None)
@given(turn_data=st.lists(interval, max_size=20), detections=segment_data, identities=speaker_data)
def test_exact_equivalence_both_modes_without_mutation(
    turn_data: list[tuple[int, int]], detections: list[tuple[str, int, int]], identities: list[tuple[str, int]],
) -> None:
    turns = [Turn(str(i), start, end) for i, (start, end) in enumerate(turn_data)]
    segments = [SpeakerSegment(label, start, end) for label, start, end in detections]
    speakers = [Speaker(label, f"anonymous-{i}", sequence) for i, (label, sequence) in enumerate(identities)]
    original = deepcopy((turns, segments, speakers))
    for exclusive in (False, True):
        expected = reference_assignment(turns, segments, speakers, require_exclusive=exclusive)
        actual = assign_turns(turns, segments, speakers, require_exclusive=exclusive)
        assert actual == expected
        # Preserve the actual input Speaker objects, not reconstructed equivalents.
        for (_, result_speaker, _), (_, expected_speaker, _) in zip(actual, expected, strict=True):
            assert result_speaker is expected_speaker
        assert (turns, segments, speakers) == original


@pytest.mark.parametrize("exclusive,expected_overlap", [(False, 160), (True, 100)])
def test_duplicate_nested_and_touching_intervals(exclusive: bool, expected_overlap: int) -> None:
    speaker = Speaker("A", "anonymous", 1)
    segments = [SpeakerSegment("A", 20, 80), SpeakerSegment("A", 0, 50), SpeakerSegment("A", 50, 100)]
    assert assign_turns([Turn("t", 0, 100)], segments, [speaker], require_exclusive=exclusive) == [
        ("t", speaker, expected_overlap),
    ]


@pytest.mark.parametrize("exclusive", [False, True])
def test_boundary_gap_degenerate_and_unordered_turns(exclusive: bool) -> None:
    speakers = [Speaker("A", "anonymous", 1), Speaker("missing", "anonymous", 2)]
    segments = [SpeakerSegment("A", 10, 20), SpeakerSegment("A", 40, 50)]
    turns = [Turn("last", 40, 50), Turn("gap", 20, 40), Turn("point", 15, 15),
             Turn("inverted", 50, 10), Turn("first", 10, 20)]
    assert assign_turns(turns, segments, speakers, require_exclusive=exclusive) == [
        ("last", speakers[0], 10), ("first", speakers[0], 10),
    ]


def test_positive_ties_preserve_sequence_then_input_order_and_ambiguity() -> None:
    speakers = [Speaker("B", "first", 2), Speaker("A", "second", 1), Speaker("C", "third", 1)]
    segments = [SpeakerSegment(label, 0, 10) for label in ("C", "B", "A")]
    turns = [Turn("t", 0, 10)]
    assert assign_turns(turns, segments, speakers) == [("t", speakers[1], 10)]
    assert assign_turns(turns, segments, speakers, require_exclusive=True) == []


def test_integer_precision_beyond_float_range() -> None:
    base = 10**20
    speakers = [Speaker("A", "anonymous", 1)]
    segments = [SpeakerSegment("A", base, base + 3), SpeakerSegment("A", base + 1, base + 4)]
    turns = [Turn("t", base + 1, base + 3)]
    assert assign_turns(turns, segments, speakers) == [("t", speakers[0], 4)]
    assert assign_turns(turns, segments, speakers, require_exclusive=True) == [("t", speakers[0], 2)]


def test_identical_detections_keep_multiplicity_only_in_accumulated_mode() -> None:
    speakers = [Speaker("A", "anonymous", 1)]
    segments = [SpeakerSegment("A", 0, 10), SpeakerSegment("A", 0, 10), SpeakerSegment("A", 2, 8)]
    turns = [Turn("t", 0, 10)]
    assert assign_turns(turns, segments, speakers) == [("t", speakers[0], 26)]
    assert assign_turns(turns, segments, speakers, require_exclusive=True) == [("t", speakers[0], 10)]


def test_benchmark_loads_anonymous_intervals_without_content(tmp_path: Path) -> None:
    benchmark = run_path(str(Path(__file__).resolve().parents[3] / "_tools" / "benchmark-assignment.py"))
    fixture = tmp_path / "intervals.json"
    fixture.write_text('{"speakers":[1],"turns":[[0,10]],"segments":[[0,0,10],[0,0,10]]}')
    turns, segments, speakers = benchmark["load_input"](fixture)
    assert assign_turns(turns, segments, speakers) == [("0", speakers[0], 20)]
    assert assign_turns(turns, segments, speakers, require_exclusive=True) == [("0", speakers[0], 10)]


@pytest.mark.parametrize("payload", [
    '{"speakers":[1],"turns":[],"segments":[],"text":"not accepted"}',
    '{"speakers":["name"],"turns":[],"segments":[]}',
    '{"speakers":[1],"turns":[[false,1]],"segments":[]}',
    '{"speakers":[1],"turns":[],"segments":[[1,0,10]]}',
])
def test_benchmark_rejects_content_and_malformed_intervals(tmp_path: Path, payload: str) -> None:
    benchmark = run_path(str(Path(__file__).resolve().parents[3] / "_tools" / "benchmark-assignment.py"))
    fixture = tmp_path / "intervals.json"
    fixture.write_text(payload)
    with pytest.raises(ValueError):
        benchmark["load_input"](fixture)
