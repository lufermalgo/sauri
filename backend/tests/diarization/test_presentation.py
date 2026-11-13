"""Final projection regressions: synthetic evidence is not acoustic qualification."""
from types import SimpleNamespace

from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.presentation import build_pieces
from app.transcription.asr_engine import TranscriptionSegment, WordInterval


def source(words: bool = True) -> TranscriptionSegment:
    return TranscriptionSegment(text="One two three.", start_ms=0, end_ms=900, words=[
        WordInterval("One", 0, 200), WordInterval(" two", 300, 500), WordInterval(" three.", 600, 900),
    ] if words else [])


def test_parent_is_preserved_and_uncertain_words_do_not_fragment() -> None:
    segment = source()
    pieces = build_pieces([SimpleNamespace(id="parent", text=segment.text, start_ms=0, end_ms=900)], [segment], [], {})
    assert pieces == [{"source_turn_id": "parent", "char_start": 0, "char_end": 14,
                       "speaker_id": None, "intervals": [{"start_ms": 0, "end_ms": 900}]}]
    assert segment.text == "One two three."


def test_change_of_voice_keeps_exact_text_offsets_and_disjoint_intervals() -> None:
    segment = source()
    regions = [SpeakerSegment("a", 0, 500), SpeakerSegment("b", 600, 900)]
    pieces = build_pieces([SimpleNamespace(id="parent", text=segment.text, start_ms=0, end_ms=900)], [segment], regions,
                          {"a": "speaker-a", "b": "speaker-b"})
    assert [(p["char_start"], p["char_end"], p["speaker_id"]) for p in pieces] == [
        (0, 7, "speaker-a"), (7, 14, "speaker-b")]
    assert pieces[0]["intervals"] == [{"start_ms": 0, "end_ms": 200}, {"start_ms": 300, "end_ms": 500}]
    assert "".join(segment.text[p["char_start"]:p["char_end"]] for p in pieces) == segment.text


def test_missing_or_invalid_words_never_assign_whole_parent_to_winner() -> None:
    for segment in [source(False), TranscriptionSegment("hello", 0, 900, [WordInterval("wrong", 0, 900)])]:
        pieces = build_pieces([SimpleNamespace(id="parent", text=segment.text, start_ms=0, end_ms=900)], [segment],
                              [SpeakerSegment("a", 0, 900)], {"a": "speaker-a"})
        assert len(pieces) == 1
        assert pieces[0]["speaker_id"] is None
        assert pieces[0]["char_end"] == len(segment.text)


def test_a_b_a_is_not_collapsed_or_reordered() -> None:
    segment = source()
    regions = [SpeakerSegment("a", 0, 200), SpeakerSegment("b", 300, 500), SpeakerSegment("a", 600, 900)]
    pieces = build_pieces([SimpleNamespace(id="parent", text=segment.text, start_ms=0, end_ms=900)],
                          [segment], regions, {"a": "speaker-a", "b": "speaker-b"})
    assert [p["speaker_id"] for p in pieces] == ["speaker-a", "speaker-b", "speaker-a"]
    assert [(p["char_start"], p["char_end"]) for p in pieces] == [(0, 3), (3, 7), (7, 14)]


def test_overlap_never_receives_an_identity() -> None:
    segment = source()
    pieces = build_pieces([SimpleNamespace(id="parent", text=segment.text, start_ms=0, end_ms=900)], [segment],
                          [SpeakerSegment("a", 0, 900), SpeakerSegment("b", 0, 900)],
                          {"a": "speaker-a", "b": "speaker-b"})
    assert len(pieces) == 1
    assert pieces[0]["speaker_id"] is None
