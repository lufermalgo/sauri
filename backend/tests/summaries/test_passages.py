"""Lossless transcript windows and grounded citation properties (spec 8/9)."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.summaries.passages import (
    SummaryInvalidError,
    Turn,
    build_passages,
    decode_key_points,
    encode_key_points,
    validate_citations,
)


@given(st.lists(st.tuples(st.text(), st.integers(0, 4_000_000), st.integers(0, 120_000))), st.integers(1, 120_000))
def test_no_turn_is_omitted_or_duplicated(rows: list[tuple[str, int, int]], window: int) -> None:
    turns = [Turn(text, start, start + duration) for text, start, duration in rows]
    passages = build_passages(turns, window)
    assert [turn for passage in passages for turn in passage.turns] == turns
    assert len({p.passage_id for p in passages}) == len(passages)
    for p in passages:
        assert all(p.start_ms <= t.start_ms <= t.end_ms <= p.end_ms for t in p.turns)


def _block(title: str, sources: list[dict[str, object]]) -> dict[str, object]:
    return {"title": title, "items": [{"text": f"{title} detail", "sub_items": ["nested"]}], "sources": sources}


def _summary(blocks: list[dict[str, object]]) -> dict[str, object]:
    return {"topic": "Synthetic", "conclusion": "Synthetic conclusion", "key_points": blocks}


@given(st.lists(st.booleans(), min_size=1, max_size=12))
def test_only_points_with_real_sources_survive(valid: list[bool]) -> None:
    passages = build_passages([Turn("Synthetic", 0, 1000)])
    summary = _summary([
        _block(str(i), [{"passage_id": "P0000" if exists else "invented", "start_ms": 99, "end_ms": 99}])
        for i, exists in enumerate(valid)
    ])
    if not any(valid):
        with pytest.raises(SummaryInvalidError, match="summary_invalid"):
            validate_citations(summary, passages)
    else:
        result = validate_citations(summary, passages)
        assert [p.title for p in result.key_points] == [str(i) for i, exists in enumerate(valid) if exists]
        assert result.review_state == "draft" and result.schema_version == 2
        assert result.conclusion == "Synthetic conclusion"
        assert all(p.sources[0].start_ms == 0 and p.sources[0].end_ms == 1000 for p in result.key_points)


def test_windows_keep_long_turns_and_speaker_labels() -> None:
    passages = build_passages([
        Turn("one", 420_000, 490_000, "Speaker 2"), Turn("two", 490_000, 500_000),
    ])
    assert len(passages) == 2
    assert passages[0].render() == "[P0000 00:07:00–00:08:10] Speaker 2: one"
    assert "Speaker ?: two" in passages[1].render()


def test_invalid_citation_is_removed_without_losing_valid_point() -> None:
    result = validate_citations(_summary([
        _block("kept", [{"passage_id": "invented"}, {"passage_id": "P0000"}]),
        _block("dropped", []),
    ]), build_passages([Turn("synthetic", 1000, 2000)]))
    assert len(result.key_points) == 1
    assert result.key_points[0].sources[0].model_dump() == {"passage_id": "P0000", "start_ms": 1000, "end_ms": 2000}
    assert result.key_points[0].items[0].sub_items == ["nested"]


@pytest.mark.parametrize("window", [0, -1])
def test_invalid_window(window: int) -> None:
    with pytest.raises(ValueError):
        build_passages([], window)


def test_non_strict_provider_limits_apply_after_invalid_sources_are_removed() -> None:
    passages = build_passages([Turn("Synthetic", i * 60_000, i * 60_000 + 1000) for i in range(6)])
    summary = _summary([
        _block("invalid", [{"passage_id": "invented"}]),
        *[_block(str(i), [
            {"passage_id": "invented"}, {}, {"passage_id": []},
            {"passage_id": "P0000"}, {"passage_id": "P0000"},
            {"passage_id": "P0001"}, {"passage_id": "P0002"}, {"passage_id": "P0003"}, {"passage_id": "P0004"},
        ]) for i in range(14)],
    ])
    result = validate_citations(summary, passages)
    assert [p.title for p in result.key_points] == [str(i) for i in range(12)]
    assert all([s.passage_id for s in p.sources] == ["P0000", "P0001", "P0002", "P0003"] for p in result.key_points)


@pytest.mark.parametrize("broken", [
    {"title": ""}, {"items": []}, {"items": [{"text": "", "sub_items": []}]},
    {"items": [{"text": "x", "sub_items": [1]}]}, {"items": [{"text": "x", "unexpected": True}]},
])
def test_malformed_v2_block_is_rejected(broken: dict[str, object]) -> None:
    passages = build_passages([Turn("synthetic", 0, 1000)])
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):
        validate_citations(_summary([{**_block("t", [{"passage_id": "P0000"}]), **broken}]), passages)


@pytest.mark.parametrize("field", ["topic", "conclusion"])
def test_v2_requires_topic_and_conclusion_within_limits(field: str) -> None:
    passages = build_passages([Turn("synthetic", 0, 1000)])
    block = _block("t", [{"passage_id": "P0000"}])
    for value in ("", "x" * 1201):
        with pytest.raises(SummaryInvalidError, match="summary_invalid"):
            validate_citations({**_summary([block]), field: value}, passages)
    missing = _summary([block])
    del missing[field]
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):
        validate_citations(missing, passages)
    assert validate_citations({**_summary([block]), field: "x" * 1200}, passages).key_points


def test_stored_v2_roundtrips_and_v1_lists_still_decode() -> None:
    passages = build_passages([Turn("synthetic", 0, 1000)])
    result = validate_citations(_summary([_block("t", [{"passage_id": "P0000"}])]), passages)
    content = decode_key_points(encode_key_points(result))
    assert (content.schema_version, content.conclusion) == (2, "Synthetic conclusion")
    assert content.key_points == [block.model_dump() for block in result.key_points]
    legacy = [{"text": "old", "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}]}, "older"]
    stored = decode_key_points(json.dumps(legacy))
    assert (stored.schema_version, stored.key_points, stored.conclusion) == (1, legacy, None)
    for unknown in ('{"schema_version": 3, "key_points": []}', '"text"', "{}"):
        with pytest.raises(ValueError):
            decode_key_points(unknown)


def _schema_caps() -> dict[str, int]:
    from app.summaries.engine import _request_schema

    block = _request_schema(["P0000"])["properties"]["key_points"]
    props = block["items"]["properties"]
    return {
        "key_points": _request_schema(["P0000"])["properties"]["key_points"]["maxItems"],
        "items": props["items"]["maxItems"],
        "sources": props["sources"]["maxItems"],
        "sub_items": props["items"]["items"]["properties"]["sub_items"]["maxItems"],
    }


def test_the_clamp_limits_are_the_schema_caps_not_a_second_copy() -> None:
    from app.summaries import passages

    caps = _schema_caps()
    used = {
        "key_points": passages.MAX_KEY_POINTS, "items": passages.MAX_ITEMS,
        "sources": passages.MAX_SOURCES, "sub_items": passages.MAX_SUB_ITEMS,
    }
    assert used == caps


def test_a_provider_that_ignores_max_items_is_clamped_instead_of_discarded() -> None:
    caps = _schema_caps()
    passages = build_passages([Turn("Synthetic", 0, 1000)])
    long_block = {
        "title": "long",
        "items": [
            {"text": f"item {i}", "sub_items": [f"sub {j}" for j in range(caps["sub_items"] + 5)]}
            for i in range(caps["items"] + 4)
        ],
        "sources": [{"passage_id": "P0000"}],
    }
    result = validate_citations(_summary([long_block]), passages)
    items = result.key_points[0].items
    assert [item.text for item in items] == [f"item {i}" for i in range(caps["items"])]  # the first ones, in order
    assert all(item.sub_items == [f"sub {j}" for j in range(caps["sub_items"])] for item in items)


def test_clamping_leaves_every_other_rule_strict() -> None:
    passages = build_passages([Turn("synthetic", 0, 1000)])
    block = _block("t", [{"passage_id": "P0000"}])
    too_long = {**block, "items": [{"text": "x" * 801, "sub_items": []}] * 20}
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):
        validate_citations(_summary([too_long]), passages)
    not_a_list = {**block, "items": "nope"}
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):
        validate_citations(_summary([not_a_list]), passages)
    bad_sub = {**block, "items": [{"text": "ok", "sub_items": [1] + ["x"] * 20}]}
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):
        validate_citations(_summary([bad_sub]), passages)
    with pytest.raises(SummaryInvalidError, match="summary_invalid"):  # an empty list is still below the minimum
        validate_citations(_summary([{**block, "items": []}]), passages)
