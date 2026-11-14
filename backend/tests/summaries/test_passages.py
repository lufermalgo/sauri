"""Lossless transcript windows and grounded citation properties (spec 8/9)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.summaries.passages import SummaryInvalidError, Turn, build_passages, validate_citations


@given(st.lists(st.tuples(st.text(), st.integers(0, 4_000_000), st.integers(0, 120_000))), st.integers(1, 120_000))
def test_no_turn_is_omitted_or_duplicated(rows: list[tuple[str, int, int]], window: int) -> None:
    turns = [Turn(text, start, start + duration) for text, start, duration in rows]
    passages = build_passages(turns, window)
    assert [turn for passage in passages for turn in passage.turns] == turns
    assert len({p.passage_id for p in passages}) == len(passages)
    for p in passages:
        assert all(p.start_ms <= t.start_ms <= t.end_ms <= p.end_ms for t in p.turns)


@given(st.lists(st.booleans(), min_size=1, max_size=12))
def test_only_points_with_real_sources_survive(valid: list[bool]) -> None:
    passages = build_passages([Turn("Synthetic", 0, 1000)])
    summary = {"topic": "Synthetic", "key_points": [
        {"text": str(i), "sources": [{"passage_id": "P0000" if exists else "invented", "start_ms": 99, "end_ms": 99}]}
        for i, exists in enumerate(valid)
    ]}
    if not any(valid):
        with pytest.raises(SummaryInvalidError, match="summary_invalid"):
            validate_citations(summary, passages)
    else:
        result = validate_citations(summary, passages)
        assert [p.text for p in result.key_points] == [str(i) for i, exists in enumerate(valid) if exists]
        assert result.review_state == "draft"
        assert all(p.sources[0].start_ms == 0 and p.sources[0].end_ms == 1000 for p in result.key_points)


def test_windows_keep_long_turns_and_speaker_labels() -> None:
    passages = build_passages([
        Turn("one", 420_000, 490_000, "Speaker 2"), Turn("two", 490_000, 500_000),
    ])
    assert len(passages) == 2
    assert passages[0].render() == "[P0000 00:07:00–00:08:10] Speaker 2: one"
    assert "Speaker ?: two" in passages[1].render()


def test_invalid_citation_is_removed_without_losing_valid_point() -> None:
    result = validate_citations({"topic": "x", "key_points": [
        {"text": "kept", "sources": [{"passage_id": "invented"}, {"passage_id": "P0000"}]},
        {"text": "dropped", "sources": []},
    ]}, build_passages([Turn("synthetic", 1000, 2000)]))
    assert len(result.key_points) == 1
    assert result.key_points[0].sources[0].model_dump() == {"passage_id": "P0000", "start_ms": 1000, "end_ms": 2000}


@pytest.mark.parametrize("window", [0, -1])
def test_invalid_window(window: int) -> None:
    with pytest.raises(ValueError):
        build_passages([], window)


def test_non_strict_provider_limits_apply_after_invalid_sources_are_removed() -> None:
    passages = build_passages([Turn("Synthetic", i * 60_000, i * 60_000 + 1000) for i in range(3)])
    summary = {"topic": "Synthetic", "key_points": [
        {"text": "invalid", "sources": [{"passage_id": "invented"}]},
        *[{"text": str(i), "sources": [
            {"passage_id": "invented"}, {}, {"passage_id": []},
            {"passage_id": "P0000"}, {"passage_id": "P0000"},
            {"passage_id": "P0001"}, {"passage_id": "P0002"},
        ]} for i in range(14)],
    ]}
    result = validate_citations(summary, passages)
    assert [p.text for p in result.key_points] == [str(i) for i in range(12)]
    assert all([s.passage_id for s in p.sources] == ["P0000", "P0001"] for p in result.key_points)
