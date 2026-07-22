"""Property tests for labeling.py.

# Feature: identificacion-hablantes, Property 7: Speaker count equals distinct raw labels
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import label_speakers


# ---------------------------------------------------------------------------
# Strategy: generate lists of SpeakerSegment with varied raw labels
# ---------------------------------------------------------------------------

raw_label_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=20,
)

segment_strategy = st.builds(
    SpeakerSegment,
    raw_label=raw_label_strategy,
    start_ms=st.integers(min_value=0, max_value=10_000_000),
    end_ms=st.integers(min_value=0, max_value=10_000_000),
).filter(lambda s: s.end_ms >= s.start_ms)


segments_list_strategy = st.lists(segment_strategy, min_size=1, max_size=30)


# ---------------------------------------------------------------------------
# Property 7: Speaker count equals distinct raw labels
# Feature: identificacion-hablantes, Property 7: Speaker count equals distinct raw labels
# Validates: Requirements 5.5, 6.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segments=segments_list_strategy)
def test_property_7_speaker_count_equals_distinct_raw_labels(
    segments: list[SpeakerSegment],
) -> None:
    """label_speakers creates exactly one Speaker per distinct raw label (bijection)."""
    result = label_speakers(segments)

    distinct_raw_labels = set(s.raw_label for s in segments)
    expected_count = len(distinct_raw_labels)

    # Verify that len(result) == number of distinct raw labels
    assert len(result) == expected_count, (
        f"Expected {expected_count} Speakers (one per distinct raw label), "
        f"but got {len(result)}"
    )

    # Verify bijection: each distinct raw label has exactly one Speaker
    raw_labels_in_result = set(sp.raw_label for sp in result)
    assert raw_labels_in_result == distinct_raw_labels, (
        f"The raw labels in the result {raw_labels_in_result} "
        f"don't match the distinct raw labels of the segments {distinct_raw_labels}"
    )

    # Verify there are no duplicate Speakers per raw label (injectivity)
    assert len(raw_labels_in_result) == len(result), (
        f"There are duplicate Speakers: {len(result)} speakers but only "
        f"{len(raw_labels_in_result)} distinct raw labels in the result"
    )


# ---------------------------------------------------------------------------
# Property 8: Anonymous, ordered, and deterministic speaker labeling
# Feature: identificacion-hablantes, Property 8: Anonymous, ordered, and deterministic speaker labeling
# Validates: Requirements 6.2, 6.3, 6.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segments=segments_list_strategy)
def test_property_8_anonymous_ordered_and_deterministic_labeling(
    segments: list[SpeakerSegment],
) -> None:
    """label_speakers orders by first start_ms with lexicographic tie-break,
    assigns consecutive sequence from 1, labels 'Speaker N', with no nominal fields."""
    result = label_speakers(segments)

    if not result:
        return

    # Compute first start_ms per raw label (reference)
    first_start: dict[str, int] = {}
    for seg in segments:
        if seg.raw_label not in first_start:
            first_start[seg.raw_label] = seg.start_ms
        else:
            first_start[seg.raw_label] = min(
                first_start[seg.raw_label], seg.start_ms
            )

    # Verify order: by (first_start_ms, raw_label) ascending (Req. 6.4)
    result_keys = [
        (first_start[sp.raw_label], sp.raw_label) for sp in result
    ]
    assert result_keys == sorted(result_keys), (
        f"Speakers are not ordered by (first_start_ms, raw_label): "
        f"{result_keys}"
    )

    # Verify consecutive sequence from 1 (Req. 6.2)
    sequences = [sp.sequence for sp in result]
    assert sequences == list(range(1, len(result) + 1)), (
        f"Sequences are not consecutive from 1: {sequences}"
    )

    # Verify label = "Speaker N" (Req. 6.2)
    for sp in result:
        assert sp.label == f"Speaker {sp.sequence}", (
            f"Incorrect label: expected 'Speaker {sp.sequence}', got '{sp.label}'"
        )

    # Verify no nominal identity fields (Req. 6.3)
    # Only has raw_label, label, and sequence — no name, email, etc.
    fields = set(result[0].__dataclass_fields__.keys())
    assert fields == {"raw_label", "label", "sequence"}, (
        f"Speaker has unexpected nominal identity fields: {fields}"
    )
