"""Source-preserving final projections. Acoustic/word evidence stays in call memory.

Only final text ranges, original playback intervals and revision-bound speaker keys
cross the commit boundary. No text is duplicated in the projection.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.diarization.diarization_engine import SpeakerSegment
from app.transcription.asr_engine import TranscriptionSegment


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FinalInterval(OutputModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class FinalPiece(OutputModel):
    source_turn_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    speaker_id: str | None
    intervals: list[FinalInterval] = Field(min_length=1)


class FinalProjection(OutputModel):
    version: int = Field(default=2, ge=2, le=2)
    transcript_id: str
    diarization_id: str
    processing_revision: int = Field(gt=0)
    policy_version: str = "exclusive-source-v1"
    pieces: list[FinalPiece]


class PreparedSpeaker(OutputModel):
    id: str
    raw_label: str
    label: str
    sequence: int


class PreparedAssignment(OutputModel):
    id: str
    turn_id: str
    speaker_id: str
    overlap_ms: int


class PreparedResult(OutputModel):
    provider: str
    speakers: list[PreparedSpeaker]
    assignments: list[PreparedAssignment]
    presentation: FinalProjection


def _union(intervals: list[dict[str, int]]) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for interval in sorted(intervals, key=lambda item: (item["start_ms"], item["end_ms"])):
        if result and interval["start_ms"] <= result[-1]["end_ms"]:
            result[-1]["end_ms"] = max(result[-1]["end_ms"], interval["end_ms"])
        else:
            result.append(dict(interval))
    return result


def build_pieces(
    sources: list[Any], segments: list[TranscriptionSegment], regions: list[SpeakerSegment],
    speaker_ids: dict[str, str],
) -> list[dict[str, Any]]:
    """Split only complete, exact and unambiguous word partitions.

    Any unavailable/ambiguous alignment keeps the *whole parent* unknown. Even a
    positive segment-level winner cannot certify an unsupported word partition.
    Character ranges count Unicode code points, not bytes or UTF-16 units.
    """
    if len(sources) != len(segments):
        raise ValueError("source alignment count mismatch")
    pieces: list[dict[str, Any]] = []
    for source, segment in zip(sources, segments, strict=True):
        if (source.text, source.start_ms, source.end_ms) != (segment.text, segment.start_ms, segment.end_ms):
            raise ValueError("source alignment mismatch")
        fallback = {"source_turn_id": source.id, "char_start": 0, "char_end": len(source.text),
                    "speaker_id": None,
                    "intervals": [{"start_ms": source.start_ms, "end_ms": source.end_ms}]}
        words = segment.words
        valid = bool(words) and "".join(word.text for word in words) == source.text
        previous_start, previous_end = source.start_ms, source.start_ms
        for word in words:
            if (type(word.start_ms) is not int or type(word.end_ms) is not int
                or not word.text.strip()
                or not source.start_ms <= word.start_ms < word.end_ms <= source.end_ms
                or word.start_ms < previous_start or word.end_ms < previous_end):
                valid = False
                break
            previous_start, previous_end = word.start_ms, word.end_ms
        labels = [{r.raw_label for r in regions
                   if min(r.end_ms, w.end_ms) > max(r.start_ms, w.start_ms)} for w in words] if valid else []
        if not valid or any(len(label) != 1 or next(iter(label)) not in speaker_ids for label in labels):
            pieces.append(fallback)
            continue
        offset = 0
        source_pieces: list[dict[str, Any]] = []
        for word, candidates in zip(words, labels, strict=True):
            speaker_id = speaker_ids[next(iter(candidates))]
            interval = {"start_ms": word.start_ms, "end_ms": word.end_ms}
            if source_pieces and source_pieces[-1]["speaker_id"] == speaker_id:
                source_pieces[-1]["char_end"] += len(word.text)
                source_pieces[-1]["intervals"].append(interval)
            else:
                source_pieces.append({"source_turn_id": source.id, "char_start": offset,
                                      "char_end": offset + len(word.text), "speaker_id": speaker_id,
                                      "intervals": [interval]})
            offset += len(word.text)
        for piece in source_pieces:
            piece["intervals"] = _union(piece["intervals"])
        pieces.extend(source_pieces)
    return pieces


def validate_projection(
    projection: FinalProjection, sources: list[Any], speaker_ids: set[str], *,
    transcript_id: str, diarization_id: str, revision: int,
) -> None:
    """Check all cross-row references before activation (and before exposing v2)."""
    if (projection.transcript_id, projection.diarization_id, projection.processing_revision) != (
        transcript_id, diarization_id, revision
    ):
        raise ValueError("projection revision mismatch")
    by_id = {s.id: s for s in sources}
    offsets = dict.fromkeys(by_id, 0)
    source_order = {s.id: i for i, s in enumerate(sorted(sources, key=lambda s: s.sequence))}
    last_order = -1
    for piece in projection.pieces:
        source = by_id.get(piece.source_turn_id)
        if (source is None or source_order[piece.source_turn_id] < last_order
            or piece.char_start != offsets[piece.source_turn_id]
            or not piece.char_start < piece.char_end <= len(source.text)
            or (piece.speaker_id is not None and piece.speaker_id not in speaker_ids)):
            raise ValueError("projection source partition mismatch")
        last_order = source_order[piece.source_turn_id]
        previous_end = -1
        for interval in piece.intervals:
            if (not source.start_ms <= interval.start_ms < interval.end_ms <= source.end_ms
                or interval.start_ms <= previous_end):
                raise ValueError("projection playback interval mismatch")
            previous_end = interval.end_ms
        offsets[piece.source_turn_id] = piece.char_end
    if any(offsets[s.id] != len(s.text) for s in sources):
        raise ValueError("projection is incomplete")


def validate_prepared(
    prepared: PreparedResult, sources: list[Any], *, transcript_id: str, diarization_id: str, revision: int,
) -> None:
    speaker_ids = {speaker.id for speaker in prepared.speakers}
    by_id = {source.id: source for source in sources}
    if (len(speaker_ids) != len(prepared.speakers)
        or len({s.raw_label for s in prepared.speakers}) != len(prepared.speakers)
        or len({a.turn_id for a in prepared.assignments}) != len(prepared.assignments)):
        raise ValueError("prepared keys are not unique")
    for assignment in prepared.assignments:
        source = by_id.get(assignment.turn_id)
        if (source is None or assignment.speaker_id not in speaker_ids
            or not 0 < assignment.overlap_ms <= source.end_ms - source.start_ms):
            raise ValueError("prepared assignment binding mismatch")
    validate_projection(prepared.presentation, sources, speaker_ids, transcript_id=transcript_id,
                        diarization_id=diarization_id, revision=revision)


def prepare_result(
    sources: list[Any], segments: list[TranscriptionSegment], regions: list[SpeakerSegment],
    domain_speakers: list[Any], domain_assignments: list[Any], provider: str,
    transcript_id: str, diarization_id: str, revision: int,
) -> PreparedResult:
    speaker_ids = {speaker.raw_label: str(uuid.uuid4()) for speaker in domain_speakers}
    projection = FinalProjection(
        transcript_id=transcript_id, diarization_id=diarization_id, processing_revision=revision,
        pieces=[FinalPiece.model_validate(piece) for piece in build_pieces(sources, segments, regions, speaker_ids)],
    )
    validate_projection(projection, sources, set(speaker_ids.values()), transcript_id=transcript_id,
                        diarization_id=diarization_id, revision=revision)
    return PreparedResult(provider=provider, presentation=projection, speakers=[
        PreparedSpeaker(id=speaker_ids[s.raw_label], raw_label=s.raw_label, label=s.label, sequence=s.sequence)
        for s in domain_speakers
    ], assignments=[PreparedAssignment(id=str(uuid.uuid4()), turn_id=turn_id,
                                      speaker_id=speaker_ids[speaker.raw_label], overlap_ms=overlap)
                    for turn_id, speaker, overlap in domain_assignments])
