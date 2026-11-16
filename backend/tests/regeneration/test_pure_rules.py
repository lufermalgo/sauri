"""#1053: pure rules behind speaker carry-over, transcript remapping and the state machine."""

from __future__ import annotations

import pytest

from app.diarization.carry_over import match_speakers
from app.diarization.remap import Span, remap_spans
from app.meetings.state_machine import apply_event
from app.regeneration.service import downstream, replaces_for


def test_unambiguous_one_to_one_speakers_are_matched() -> None:
    overlap = {("n1", "o1"): 900, ("n2", "o2"): 800, ("n1", "o2"): 50}
    assert match_speakers(overlap, {"n1": 1000, "n2": 850}, {"o1": 950, "o2": 900}) == {"n1": "o1", "n2": "o2"}


def test_a_merged_or_split_speaker_is_never_matched() -> None:
    # Two old speakers folded into one new one: neither share reaches the threshold.
    merged = {("n", "a"): 500, ("n", "b"): 500}
    assert match_speakers(merged, {"n": 1000}, {"a": 500, "b": 500}) == {}
    # One old speaker split in two: each new half covers too little of the old speaker.
    split = {("x", "o"): 520, ("y", "o"): 480}
    assert match_speakers(split, {"x": 520, "y": 480}, {"o": 1000}) == {}


def test_a_speaker_must_be_the_best_match_in_both_directions() -> None:
    overlap = {("n1", "o"): 900, ("n2", "o"): 950}
    assert match_speakers(overlap, {"n1": 900, "n2": 1000}, {"o": 1000}) == {"n2": "o"}


def test_remap_takes_the_largest_overlap_and_falls_back_only_when_asked() -> None:
    old = [Span(0, 1000, "A"), Span(1000, 3000, "B")]
    new = [(0, 900), (900, 2000), (2900, 3500), (5000, 5200), (500, 500)]
    assert remap_spans(old, new, nearest=False) == ["A", "B", "B", None, None]
    assert remap_spans(old, new, nearest=True) == ["A", "B", "B", "B", "A"]
    assert remap_spans([], new, nearest=True) == [None] * 5


def test_remap_handles_unsorted_new_spans() -> None:
    old = [Span(0, 100, "A"), Span(100, 200, "B")]
    assert remap_spans(old, [(120, 190), (10, 90)], nearest=False) == ["B", "A"]


def test_only_an_explicit_event_reopens_a_finished_meeting() -> None:
    for state in ("completed", "failed"):
        assert apply_event(state, "regeneration_started").new_state == "transcribing"
        for event in ("start_capture", "recording_uploaded", "transcription_completed", "engine_failed",
                      "regeneration_failed"):
            assert apply_event(state, event).successful is False
    assert apply_event("transcribing", "regeneration_failed").new_state == "completed"
    assert apply_event("queued", "regeneration_started").successful is False
    assert apply_event("transcribing", "regeneration_started").successful is False


@pytest.mark.parametrize(("stage", "cascade", "expected"), [
    ("transcription", False, ["transcription"]),
    ("transcription", True, ["transcription", "speakers", "summary"]),
    ("speakers", True, ["speakers", "summary"]),
    ("summary", False, ["summary"]),
])
def test_replaces_follow_the_pipeline_order(stage: str, cascade: bool, expected: list[str]) -> None:
    assert replaces_for(stage, cascade) == expected  # type: ignore[arg-type]
    assert downstream("summary") == ()
