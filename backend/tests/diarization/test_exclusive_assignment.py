"""Delta #880: honest optional attribution without modifying legacy behavior."""

from types import SimpleNamespace

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import label_speakers


def test_aligned_words_expose_both_speakers_without_fabricated_boundaries() -> None:
    segments = [SpeakerSegment("A", 2000, 2600), SpeakerSegment("B", 2600, 3000), SpeakerSegment("C", 3100, 3300)]
    speakers = label_speakers(segments)
    words = [
        SimpleNamespace(id="w1", start_ms=2000, end_ms=2600),
        SimpleNamespace(id="w2", start_ms=2600, end_ms=2800),
        SimpleNamespace(id="w3", start_ms=2800, end_ms=3000),
    ]
    assigned = assign_turns(words, segments, speakers, require_exclusive=True)
    assert [(turn_id, speaker.raw_label, overlap) for turn_id, speaker, overlap in assigned] == [
        ("w1", "A", 600),
        ("w2", "B", 200),
        ("w3", "B", 200),
    ]
    assert len(speakers) == 3  # C is not hidden just because it has no text.


def test_ambiguous_words_and_whole_segment_fallback_have_no_exclusive_identity() -> None:
    segments = [SpeakerSegment("A", 0, 600), SpeakerSegment("B", 500, 1000)]
    speakers = label_speakers(segments)
    turns = [
        SimpleNamespace(id="ambiguous", start_ms=500, end_ms=700),
        SimpleNamespace(id="whole", start_ms=0, end_ms=1000),
        SimpleNamespace(id="none", start_ms=1100, end_ms=1200),
    ]
    assert assign_turns(turns, segments, speakers, require_exclusive=True) == []
    assert len(assign_turns(turns, segments, speakers)) == 2  # legacy stays explicit


def test_duplicate_detections_do_not_inflate_positive_evidence() -> None:
    segments = [SpeakerSegment("A", 0, 600), SpeakerSegment("A", 300, 700)]
    assigned = assign_turns(
        [SimpleNamespace(id="w", start_ms=0, end_ms=1000)], segments, label_speakers(segments), require_exclusive=True
    )
    assert assigned[0][2] == 700
