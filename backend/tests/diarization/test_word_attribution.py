"""Word-level attribution and turn grouping (core-speech-pipeline U3.2, Requirement 4).

Properties 1, 2, 3 and 6 of design.md plus boundary cases of the 40/25/20 rule.
"""

from __future__ import annotations

from typing import Literal

from hypothesis import given
from hypothesis import strategies as st

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.word_attribution import (
    WordAttribution,
    WordTime,
    attribute_words,
    group_words_into_turns,
)

LABELS = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


@st.composite
def words_strategy(draw: st.DrawFn, *, min_duration: int = 0, max_gap: int = 3000) -> list[WordTime]:
    count = draw(st.integers(min_value=0, max_value=40))
    words: list[WordTime] = []
    cursor = draw(st.integers(min_value=0, max_value=2000))
    for sequence in range(count):
        cursor += draw(st.integers(min_value=0, max_value=max_gap))
        duration = draw(st.integers(min_value=min_duration, max_value=1000))
        text = draw(st.text(alphabet=" abc\u00f1\u00e9.,", max_size=6))
        words.append(WordTime(sequence, text, cursor, cursor + duration))
        cursor += duration
    return words


@st.composite
def segments_strategy(draw: st.DrawFn) -> list[SpeakerSegment]:
    """Arbitrary, possibly overlapping and duplicated, diarization output."""
    return draw(
        st.lists(
            st.builds(
                lambda label, start, duration: SpeakerSegment(label, start, start + duration),
                st.sampled_from(LABELS),
                st.integers(min_value=0, max_value=60_000),
                st.integers(min_value=0, max_value=8000),
            ),
            max_size=20,
        )
    )


@st.composite
def exclusive_timeline(draw: st.DrawFn) -> tuple[list[WordTime], list[SpeakerSegment]]:
    """Non-overlapping segments and dense words (<= 1 s, gaps <= 300 ms) spanning them."""
    segments: list[SpeakerSegment] = []
    cursor = 0
    for _ in range(draw(st.integers(min_value=1, max_value=8))):
        cursor += draw(st.integers(min_value=0, max_value=1000))
        duration = draw(st.integers(min_value=300, max_value=8000))
        segments.append(SpeakerSegment(draw(st.sampled_from(LABELS)), cursor, cursor + duration))
        cursor += duration
    words: list[WordTime] = []
    position = draw(st.integers(min_value=0, max_value=300))
    while position < cursor:
        duration = draw(st.integers(min_value=20, max_value=1000))
        words.append(WordTime(len(words), " w", position, position + duration))
        position += duration + draw(st.integers(min_value=0, max_value=300))
    return words, segments


# --- Property 1: text conservation -------------------------------------------------


@given(words=words_strategy(), segments=segments_strategy())
def test_property_1_text_and_word_count_are_conserved(words: list[WordTime], segments: list[SpeakerSegment]) -> None:
    attributions = attribute_words(words, segments)
    turns = group_words_into_turns(words, attributions)

    assert len(attributions) == len(words)
    assert [a.word_sequence for a in attributions] == [w.sequence for w in words]
    assert "".join(turn.text for turn in turns) == "".join(word.text for word in words)
    assert sum(turn.word_count for turn in turns) == len(words)
    assert [turn.sequence for turn in turns] == list(range(1, len(turns) + 1))


# --- Property 2: determinism and segment-order invariance ---------------------------


@given(words=words_strategy(), segments=segments_strategy(), data=st.data())
def test_property_2_deterministic_and_independent_of_segment_order(
    words: list[WordTime], segments: list[SpeakerSegment], data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(segments))
    first = attribute_words(words, segments)
    assert attribute_words(words, segments) == first
    assert attribute_words(words, shuffled) == first


# --- Property 3: a speaker with >= 5 s of speech is visible -------------------------


@given(timeline=exclusive_timeline())
def test_property_3_label_with_five_seconds_gets_an_assigned_word(
    timeline: tuple[list[WordTime], list[SpeakerSegment]],
) -> None:
    words, segments = timeline
    attributions = attribute_words(words, segments)
    assigned_labels = {a.raw_label for a in attributions if a.state == "assigned"}
    for segment in segments:
        overlapped = any(w.start_ms < segment.end_ms and segment.start_ms < w.end_ms for w in words)
        if segment.end_ms - segment.start_ms >= 5000 and overlapped:
            assert segment.raw_label in assigned_labels


# --- Property 6: ambiguity keeps candidates ----------------------------------------


@given(words=words_strategy(), segments=segments_strategy())
def test_property_6_candidates_by_state(words: list[WordTime], segments: list[SpeakerSegment]) -> None:
    for attribution in attribute_words(words, segments):
        if attribution.state == "ambiguous":
            assert attribution.raw_label is None
            assert len(attribution.candidates) >= 2
            assert all(0 < fraction <= 1 for _, fraction in attribution.candidates)
        elif attribution.state == "unassigned":
            assert attribution.raw_label is None
            assert attribution.candidates == ()
        else:
            assert attribution.raw_label is not None


# --- Unit cases ---------------------------------------------------------------------


def _single(word: WordTime, segments: list[SpeakerSegment]) -> WordAttribution:
    return attribute_words([word], segments)[0]


def test_segments_with_300ms_gaps_leave_no_word_unassigned() -> None:
    segments = [
        SpeakerSegment("A" if i % 2 == 0 else "B", i * 1300, i * 1300 + 1000) for i in range(20)
    ]
    words = [WordTime(i, " w", i * 130, i * 130 + 100) for i in range(200)]
    attributions = attribute_words(words, segments)
    assert all(a.state != "unassigned" for a in attributions)


def test_word_in_two_second_gap_without_nearby_segment_is_unassigned() -> None:
    segments = [SpeakerSegment("A", 0, 1000), SpeakerSegment("B", 3000, 4000)]
    assert _single(WordTime(0, " x", 1600, 2400), segments) == WordAttribution(0, None, "unassigned", ())


def test_nearest_segment_within_500ms_assigns_its_label() -> None:
    segments = [SpeakerSegment("A", 0, 1000), SpeakerSegment("B", 1800, 3000)]
    assert _single(WordTime(0, " x", 1400, 1500), segments) == WordAttribution(0, "B", "assigned", ())
    assert _single(WordTime(0, " x", 1500, 1500), [SpeakerSegment("A", 0, 1000)]).state == "assigned"
    assert _single(WordTime(0, " x", 1501, 1600), [SpeakerSegment("A", 0, 1000)]).state == "unassigned"


def test_nearest_ties_break_by_raw_label() -> None:
    segments = [SpeakerSegment("B", 0, 1000), SpeakerSegment("A", 1200, 2000)]
    assert _single(WordTime(0, " x", 1050, 1150), segments).raw_label == "A"


def test_top_at_forty_percent_is_assigned_and_below_falls_back() -> None:
    # d = 100; A covers 40 ms -> assigned.
    assert _single(WordTime(0, " x", 0, 100), [SpeakerSegment("A", 60, 2000)]).raw_label == "A"
    # A covers 39 ms and no other segment -> nearest (gap 0) still A, without candidates.
    fallback = _single(WordTime(0, " x", 0, 100), [SpeakerSegment("A", 61, 2000)])
    assert fallback == WordAttribution(0, "A", "assigned", ())


def test_second_at_twenty_five_percent_with_small_margin_is_ambiguous() -> None:
    # d = 100; A = 44, B = 25, margin 19 < 20 -> ambiguous.
    segments = [SpeakerSegment("A", 0, 44), SpeakerSegment("B", 75, 100)]
    result = _single(WordTime(0, " x", 0, 100), segments)
    assert result == WordAttribution(0, None, "ambiguous", (("A", 0.44), ("B", 0.25)))


def test_second_below_twenty_five_percent_is_assigned() -> None:
    # A = 44, B = 24 -> second under threshold.
    segments = [SpeakerSegment("A", 0, 44), SpeakerSegment("B", 76, 100)]
    assert _single(WordTime(0, " x", 0, 100), segments).raw_label == "A"


def test_margin_of_exactly_twenty_percent_is_assigned() -> None:
    # A = 45, B = 25, margin 20 is not < 20.
    segments = [SpeakerSegment("A", 0, 45), SpeakerSegment("B", 75, 100)]
    assert _single(WordTime(0, " x", 0, 100), segments).raw_label == "A"


def test_tied_overlap_is_ambiguous_with_candidates_sorted_by_label() -> None:
    segments = [SpeakerSegment("B", 50, 100), SpeakerSegment("A", 0, 50)]
    result = _single(WordTime(0, " x", 0, 100), segments)
    assert result.state == "ambiguous"
    assert result.candidates == (("A", 0.5), ("B", 0.5))


def test_short_and_zero_length_words_use_minimum_duration() -> None:
    # Zero-length word at 1000 is queried as [990, 1010] with d = 20.
    assert _single(WordTime(0, " x", 1000, 1000), [SpeakerSegment("A", 1000, 2000)]).raw_label == "A"
    # A 5 ms word fully inside A: 5/20 < 40 %, falls back to nearest (gap 0).
    assert _single(WordTime(0, " x", 1500, 1505), [SpeakerSegment("A", 1000, 2000)]).raw_label == "A"


def test_duplicate_detections_of_one_label_count_as_union() -> None:
    segments = [SpeakerSegment("A", 0, 30), SpeakerSegment("A", 0, 30), SpeakerSegment("B", 30, 100)]
    assert _single(WordTime(0, " x", 0, 100), segments).raw_label == "B"


def _attr(
    sequence: int, label: str | None, state: Literal["assigned", "unassigned"] = "assigned"
) -> WordAttribution:
    return WordAttribution(sequence, label, state, ())


def test_grouping_changes_turn_on_label_change_and_keeps_unassigned_and_ambiguous() -> None:
    words = [
        WordTime(0, " Hola", 0, 300),
        WordTime(1, " que", 400, 600),
        WordTime(2, " tal", 700, 900),
        WordTime(3, " bien", 1000, 1200),
        WordTime(4, ",", 1200, 1210),
    ]
    attributions = [
        _attr(0, "A"),
        _attr(1, None, "unassigned"),
        WordAttribution(2, None, "ambiguous", (("A", 0.5), ("B", 0.5))),
        _attr(3, "B"),
        _attr(4, None, "unassigned"),
    ]
    turns = group_words_into_turns(words, attributions)
    assert [(t.raw_label, t.text, t.word_count, t.has_ambiguous, t.start_ms, t.end_ms) for t in turns] == [
        ("A", " Hola que tal", 3, True, 0, 900),
        ("B", " bien,", 2, False, 1000, 1210),
    ]


def test_grouping_adopts_first_assigned_label_after_leading_unassigned_words() -> None:
    words = [WordTime(0, " eh", 0, 100), WordTime(1, " si", 200, 300), WordTime(2, " no", 400, 500)]
    attributions = [_attr(0, None, "unassigned"), _attr(1, "B"), _attr(2, "A")]
    turns = group_words_into_turns(words, attributions)
    assert [(t.sequence, t.raw_label, t.text) for t in turns] == [(1, "B", " eh si"), (2, "A", " no")]


def test_grouping_splits_on_gap_longer_than_two_seconds() -> None:
    words = [WordTime(0, " a", 0, 100), WordTime(1, " b", 2100, 2200), WordTime(2, " c", 4201, 4300)]
    attributions = [_attr(0, "A"), _attr(1, "A"), _attr(2, "A")]
    turns = group_words_into_turns(words, attributions)
    assert [(t.raw_label, t.text) for t in turns] == [("A", " a b"), ("A", " c")]


def test_grouping_of_no_words_is_empty() -> None:
    assert group_words_into_turns([], []) == []
