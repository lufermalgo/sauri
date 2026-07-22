"""Property tests for diarization_engine.py.

# Feature: identificacion-hablantes, Property 6: Ascending order of SpeakerSegments
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.diarization_engine import DiarizationResult, SpeakerSegment


# ---------------------------------------------------------------------------
# Strategy: generate lists of SpeakerSegment with valid constraints
# ---------------------------------------------------------------------------

segment_strategy = st.builds(
    SpeakerSegment,
    raw_label=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=20,
    ),
    start_ms=st.integers(min_value=0, max_value=10_000_000),
    end_ms=st.integers(min_value=0, max_value=10_000_000),
).filter(lambda s: s.end_ms >= s.start_ms)


segments_list_strategy = st.lists(segment_strategy, min_size=0, max_size=30)


# ---------------------------------------------------------------------------
# Property 6: Ascending order of SpeakerSegments
# Feature: identificacion-hablantes, Property 6: Ascending order of SpeakerSegments
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segments=segments_list_strategy)
def test_property_6_diarization_result_ascending_order(
    segments: list[SpeakerSegment],
) -> None:
    """A valid DiarizationResult has segments non-decreasingly ordered by start_ms."""
    result = DiarizationResult(
        segments=segments,
        speaker_count=len(set(s.raw_label for s in segments)),
    )

    for i in range(1, len(result.segments)):
        assert result.segments[i].start_ms >= result.segments[i - 1].start_ms, (
            f"Segment at position {i} has start_ms={result.segments[i].start_ms} "
            f"lower than the previous start_ms={result.segments[i - 1].start_ms}"
        )
