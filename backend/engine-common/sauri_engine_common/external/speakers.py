"""Shared pieces of the external speaker diarization adapters (``assemblyai``, ``deepgram``).

Normalized result
    Every adapter returns a ``DiarResult`` whose times are in milliseconds on the clock of the prepared
    part it was given. ``SpeakerSegment`` has the fields of ``SpeakerSegment`` in
    ``app/diarization/diarization_engine.py`` (``raw_label``, ``start_ms``, ``end_ms``); ``to_payload``
    gives the gateway answer shape (``speaker``, ``start_ms``, ``end_ms``) that the local Senko engine
    returns. Adapters never apply ``offset_ms``: ``merge_parts`` is the only place where it happens.

Exact union (design Property 8)
    ``union_runs`` joins consecutive labelled words (in time order) with the same label into one segment
    that starts at the first word and ends at the last one. There is no duration filter and no padding:
    a one-word, zero-length run is a segment. ``speaker_count`` is the number of distinct labels. A word
    without a label is skipped (it neither extends nor breaks a run) and counted in diagnostics.

No provider text (design Property 4)
    ``LabeledWord`` has no text field: adapters read ``text``/``word`` only to decide whether the part has
    speech at all and drop it before building words. Labels are checked against a short alphabet so a
    provider cannot smuggle content through them. Nothing here logs.

Labels across parts (conservative policy)
    Provider labels are anonymous and local to one job (``A`` in part 1 is not known to be ``A`` in part
    2). ``merge_parts`` therefore keeps labels distinct per part (``p1.A``, ``p2.A``) and reports it in
    ``diagnostics["label_policy"] == "per_part"`` (``"provider"`` for a single part); ``speaker_count``
    of a merged result counts those per-part labels, so it can over-count real people, and
    ``diagnostics["speaker_count_per_part"]`` gives the count of each part.
    A caller that can tell identities apart (for example by voice embeddings) passes ``identity`` to
    link specific ``(part_index, label)`` pairs; nothing is guessed.
    One part is passed through with the provider labels unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from sauri_engine_common.external.asr_common import invalid
from sauri_engine_common.external.errors import ProviderError

_LABEL: Final = re.compile(r"[A-Za-z0-9_-]{1,16}")
PER_PART: Final = "per_part"


@dataclass(frozen=True)
class SpeakerSegment:
    raw_label: str
    start_ms: int
    end_ms: int

    def to_payload(self) -> dict[str, object]:
        """The segment as the diarization gateway answers it (``speaker`` instead of ``raw_label``)."""
        return {"speaker": self.raw_label, "start_ms": self.start_ms, "end_ms": self.end_ms}


@dataclass(frozen=True)
class LabeledWord:
    """A word reduced to what diarization needs: who and when. The provider's text is already gone."""

    label: str | None
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class DiarResult:
    segments: tuple[SpeakerSegment, ...]
    speaker_count: int
    audio_ms: int | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict, compare=False)


def safe_label(value: object) -> str | None:
    """A provider label (a string or a non-negative integer) as a short safe string; ``None`` when absent."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise invalid("bad_speaker_label")
    label = str(value)
    if (isinstance(value, int) and value < 0) or _LABEL.fullmatch(label) is None:
        raise invalid("bad_speaker_label")
    return label


def union_runs(words: Iterable[LabeledWord]) -> tuple[SpeakerSegment, ...]:
    """Segments of consecutive same-label words: exact interval, no filter (Property 8).

    Words are taken in time order (stable on ties). Times are used as given; ``clamp_words`` repairs
    them beforehand.
    """
    labelled = sorted((w for w in words if w.label is not None), key=lambda w: w.start_ms)
    segments: list[SpeakerSegment] = []
    for word in labelled:
        assert word.label is not None
        last = segments[-1] if segments else None
        if last is not None and last.raw_label == word.label:
            segments[-1] = replace(last, end_ms=max(last.end_ms, word.end_ms))
        else:
            segments.append(SpeakerSegment(word.label, word.start_ms, word.end_ms))
    return tuple(segments)


def clamp_words(words: Sequence[LabeledWord], audio_ms: int | None) -> tuple[list[LabeledWord], int]:
    """Repair what a provider reports (negative start, end before start, end past the audio).

    Returns the words and how many were repaired. Times are never invented.
    """
    out: list[LabeledWord] = []
    repaired = 0
    for word in words:
        start = max(word.start_ms, 0)
        end = max(word.end_ms, start)
        if audio_ms is not None and end > audio_ms:
            end = audio_ms
            start = min(start, end)
        repaired += (start, end) != (word.start_ms, word.end_ms)
        out.append(replace(word, start_ms=start, end_ms=end))
    return out, repaired


def build_result(
    words: Sequence[LabeledWord],
    *,
    has_speech: bool,
    audio_ms: int | None,
    diagnostics: Mapping[str, object] | None = None,
) -> DiarResult:
    """Validate labelled words into a ``DiarResult``.

    ``has_speech`` says the provider found speech (it returned words or text). Speech without a single
    label is rejected (``provider_invalid_output``, reason ``no_speaker_labels``): speakers are not
    invented. Silence (no words) is a valid, empty result.
    """
    cleaned, repaired = clamp_words(words, audio_ms)
    segments = union_runs(cleaned)
    if has_speech and not segments:
        raise ProviderError("provider_invalid_output", reason="no_speaker_labels")
    unlabeled = sum(1 for w in cleaned if w.label is None)
    info: dict[str, object] = {**(diagnostics or {}), "timing_repaired": repaired, "unlabeled_words": unlabeled}
    return DiarResult(segments, len({s.raw_label for s in segments}), audio_ms, info)


def merge_parts(
    results: Sequence[DiarResult],
    offsets: Sequence[int],
    *,
    identity: Mapping[tuple[int, str], str] | None = None,
) -> DiarResult:
    """Put the parts on the original clock and keep speaker labels distinct per part.

    ``offsets`` are the ``offset_ms`` of each part from ``audio_prep``; parts are ordered by offset and
    ``part_index`` is the position after that order. One part returns its labels unchanged. With several,
    each label becomes ``p<part_index + 1>.<label>`` unless ``identity`` maps ``(part_index, label)`` to
    a label the caller vouches for (it is used as is; it must match the label alphabet). Times are only
    shifted: segments of different speakers may overlap and are not trimmed. The result is sorted by
    ``(start_ms, end_ms, raw_label)``.
    """
    if not results or len(results) != len(offsets) or any(offset < 0 for offset in offsets):
        raise ValueError("invalid_parts")
    ordered = sorted(zip(offsets, results, strict=True), key=lambda pair: pair[0])
    links = dict(identity or {})
    for target in links.values():
        if _LABEL.fullmatch(target) is None:
            raise ValueError("invalid_identity")
    single = len(ordered) == 1
    segments: list[SpeakerSegment] = []
    for index, (offset, result) in enumerate(ordered):
        for segment in result.segments:
            label = (
                segment.raw_label
                if single
                else links.get((index, segment.raw_label), f"p{index + 1}.{segment.raw_label}")
            )
            segments.append(SpeakerSegment(label, segment.start_ms + offset, segment.end_ms + offset))
    segments.sort(key=lambda s: (s.start_ms, s.end_ms, s.raw_label))
    last_offset, last = ordered[-1]
    audio_ms = None if last.audio_ms is None else last_offset + last.audio_ms
    diagnostics: dict[str, object] = {
        "parts": len(ordered),
        "label_policy": "provider" if single else "per_part_with_identity" if links else PER_PART,
        "speaker_count_per_part": [r.speaker_count for _o, r in ordered],
        "timing_repaired": sum(int(str(r.diagnostics.get("timing_repaired", 0))) for _o, r in ordered),
    }
    deleted = [r.diagnostics["remote_deleted"] for _o, r in ordered if "remote_deleted" in r.diagnostics]
    if deleted:
        diagnostics["remote_deleted"] = all(deleted)
    return DiarResult(tuple(segments), len({s.raw_label for s in segments}), audio_ms, diagnostics)
