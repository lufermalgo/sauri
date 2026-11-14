"""Tests for the pure whisper.cpp token-to-word conversion (hand-written fixtures only)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "whisper_words.py"
MODULE_SPEC = importlib.util.spec_from_file_location("whisper_words", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
ww = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = ww
MODULE_SPEC.loader.exec_module(ww)


def tok(text: str, start: int, end: int, *, id_: int = 100, p: float = 0.9) -> dict[str, Any]:
    return {"text": text, "id": id_, "p": p, "offsets": {"from": start, "to": end}}


def seg(text: str, tokens: list[dict[str, Any]], start: int = 0, end: int = 1000) -> dict[str, Any]:
    return {"offsets": {"from": start, "to": end}, "text": text, "tokens": tokens}


def test_merges_subword_tokens_and_skips_special_tokens() -> None:
    doc = {
        "transcription": [
            seg(
                " Hola mundo",
                [
                    tok("[_BEG_]", 0, 0, id_=50364),
                    tok(" Ho", 0, 200, p=0.9),
                    tok("la", 150, 400, p=0.5),
                    tok(" mundo", 400, 900, p=0.8),
                    tok("<|endoftext|>", 900, 900, id_=50257),
                ],
            )
        ]
    }
    result = ww.words_from_ggml_json(doc, 5000)
    words = result.segments[0].words
    assert [w.text for w in words] == [" Hola", " mundo"]
    assert (words[0].start_ms, words[0].end_ms, words[0].probability) == (0, 400, 0.5)
    assert (words[1].start_ms, words[1].end_ms) == (400, 900)
    assert result.inverted_words == 0
    assert not any(w.timing_repaired for w in words)


def test_newline_and_tab_start_new_words() -> None:
    doc = {"transcription": [seg("a b c", [tok(" a", 0, 10), tok("\nb", 10, 20), tok("\tc", 20, 30)])]}
    assert [w.text for w in ww.words_from_ggml_json(doc, 100).segments[0].words] == [" a", "\nb", "\tc"]


def test_inverted_word_is_repaired_to_previous_valid_end() -> None:
    doc = {"transcription": [seg(" a b c", [tok(" a", 0, 300), tok(" b", 500, 400), tok(" c", 600, 700)])]}
    result = ww.words_from_ggml_json(doc, 5000)
    a, b, c = result.segments[0].words
    assert (b.start_ms, b.end_ms, b.timing_repaired) == (300, 300, True)
    assert (a.timing_repaired, c.timing_repaired) == (False, False)
    assert (c.start_ms, c.end_ms) == (600, 700)
    assert result.inverted_words == 1


def test_first_word_negative_start_repairs_to_zero() -> None:
    doc = {"transcription": [seg(" a", [tok(" a", -5, 100)])]}
    result = ww.words_from_ggml_json(doc, 5000)
    word = result.segments[0].words[0]
    assert (word.start_ms, word.end_ms, word.timing_repaired) == (0, 0, True)
    assert result.inverted_words == 1


def test_previous_valid_end_spans_segments() -> None:
    doc = {
        "transcription": [
            seg(" a", [tok(" a", 0, 250)]),
            seg(" b", [tok(" b", 900, 800)], 800, 1000),
        ]
    }
    result = ww.words_from_ggml_json(doc, 5000)
    assert (result.segments[1].words[0].start_ms, result.segments[1].words[0].end_ms) == (250, 250)


def test_clamps_to_audio_duration() -> None:
    doc = {"transcription": [seg(" a b", [tok(" a", 100, 900), tok(" b", 1200, 1500)], 0, 1600)]}
    result = ww.words_from_ggml_json(doc, 1000)
    a, b = result.segments[0].words
    assert (a.start_ms, a.end_ms) == (100, 900)
    assert (b.start_ms, b.end_ms) == (1000, 1000)
    assert (result.segments[0].start_ms, result.segments[0].end_ms) == (0, 1000)


def test_segment_with_text_and_no_words_raises() -> None:
    doc = {"transcription": [seg(" hola", [tok("[_BEG_]", 0, 0, id_=50364)])]}
    with pytest.raises(ww.NoWordTimestampsError, match="no_word_timestamps"):
        ww.words_from_ggml_json(doc, 1000)


def test_blank_segment_without_words_is_allowed() -> None:
    result = ww.words_from_ggml_json({"transcription": [seg("  ", [])]}, 1000)
    assert result.segments[0].words == ()


_times = st.integers(min_value=-2000, max_value=20000)


@st.composite
def _word_tokens(draw: st.DrawFn) -> list[tuple[int, int]]:
    return draw(st.lists(st.tuples(_times, _times), min_size=1, max_size=30))


@given(_word_tokens())
def test_property_4_inverted_tokens_are_repaired_and_valid_ones_unchanged(times: list[tuple[int, int]]) -> None:
    audio_ms = 100_000  # large enough that clamping never interferes
    doc = {"transcription": [seg("x", [tok(f" w{i}", s, e) for i, (s, e) in enumerate(times)])]}
    result = ww.words_from_ggml_json(doc, audio_ms)
    words = result.segments[0].words
    previous_end = 0
    expected_inverted = 0
    for (s, e), word in zip(times, words, strict=True):
        if e < s or s < 0:
            expected_inverted += 1
            assert (word.start_ms, word.end_ms, word.timing_repaired) == (previous_end, previous_end, True)
        else:
            assert (word.start_ms, word.end_ms, word.timing_repaired) == (s, e, False)
            previous_end = e
    assert result.inverted_words == expected_inverted


@given(_word_tokens(), st.integers(min_value=0, max_value=20000))
def test_property_5_start_never_after_end(times: list[tuple[int, int]], audio_ms: int) -> None:
    doc = {"transcription": [seg("x", [tok(f" w{i}", s, e) for i, (s, e) in enumerate(times)])]}
    for segment in ww.words_from_ggml_json(doc, audio_ms).segments:
        for word in segment.words:
            assert 0 <= word.start_ms <= word.end_ms <= audio_ms
