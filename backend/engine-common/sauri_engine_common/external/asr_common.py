"""Shared pieces of the external transcription adapters (``openai-audio``, ``assemblyai``, ``deepgram``).

Normalized result
    Every adapter returns an ``AsrResult`` whose times are in milliseconds on the clock of the prepared
    part it was given. ``merge_parts`` moves several parts onto the original clock with the ``offset_ms``
    reported by ``audio_prep`` and enforces monotonic, non-overlapping times. Adapters never apply the
    offset themselves, so there is exactly one place where it happens.

No fabricated times (design Property 7)
    ``build_result`` only repairs what a provider reports (a negative start, an end before the start, an
    end past the audio duration) by clamping, and flags the word with ``timing_repaired``. A provider
    answer that has text but no word times raises ``no_word_timestamps``; times are never interpolated.

Transport
    Adapters do not own a socket. They receive an ``HttpTransport``: the host service's ``SafeHttp``
    (the single outbound path with the address policy, pinning and body caps) satisfies it as is, and the
    SSRF logic is not duplicated here.

Content hygiene (design Property 4)
    Nothing in this package logs, stores or raises a key, an ``Authorization`` header, audio, a transcript
    or a provider body. Errors are ``ProviderError`` values (class code and short reason) and
    ``AdapterCancelled``; the only text taken from a provider error body is a short code of
    ``[A-Za-z0-9_.:-]`` characters, used to classify and never re-emitted.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Protocol

from sauri_engine_common.external.errors import ProviderError, classify

UNDETERMINED: Final = "und"
AUTO: Final = "auto"
# Largest overlap between consecutive words (or segments) that merge_parts trims. Whisper-style decoders
# overlap neighbours by tens of milliseconds; a bigger overlap means the provider output is inconsistent.
MAX_OVERLAP_TRIM_MS: Final = 500
# A segment with text must have a word within this distance of it, otherwise the words are incomplete.
SEGMENT_COVERAGE_SLACK_MS: Final = 250

_HINT: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class AdapterCancelled(Exception):  # noqa: N818 - a control-flow signal, not a failure class
    """The caller's cancel event was set; the HTTP request was aborted and remote work was cleaned up."""

    code = "cancelled"


@dataclass(frozen=True)
class ProviderLimits:
    """Upload limits a caller passes to ``audio_prep``; ``verified_on`` stays ``None`` until U10."""

    max_upload_bytes: int | None
    max_audio_s: int | None
    verified_on: str | None = None


@dataclass(frozen=True)
class AsrWord:
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None
    timing_repaired: bool = False


@dataclass(frozen=True)
class AsrSegment:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AsrResult:
    """Words (and optional segments) of one prepared part, in milliseconds on the part clock."""

    words: tuple[AsrWord, ...]
    language: str
    segments: tuple[AsrSegment, ...] = ()
    audio_ms: int | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict, compare=False)


# --- transport ----------------------------------------------------------------------------------------


class HttpResponse(Protocol):
    @property
    def status(self) -> int: ...
    @property
    def retry_after(self) -> str | None: ...
    @property
    def body(self) -> bytes: ...


class HttpTransport(Protocol):
    """Same call shape as ``SafeHttp.request`` in ``host-engine/providers.py``."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        allow_local: bool,
        total_timeout_s: float,
        connect_timeout_s: float = ...,
    ) -> HttpResponse: ...


async def send(
    http: HttpTransport,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None,
    cancel: asyncio.Event,
    allow_local: bool,
    total_timeout_s: float,
    connect_timeout_s: float,
) -> HttpResponse:
    """One request that is aborted (the connection closed) as soon as ``cancel`` is set."""
    if cancel.is_set():
        raise AdapterCancelled
    request = asyncio.ensure_future(
        http.request(
            method,
            url,
            headers=headers,
            body=body,
            allow_local=allow_local,
            total_timeout_s=total_timeout_s,
            connect_timeout_s=connect_timeout_s,
        )
    )
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        await asyncio.wait({request, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if request.done():
            return request.result()
        raise AdapterCancelled
    finally:
        for task in (request, waiter):
            if not task.done():
                task.cancel()
        await asyncio.gather(request, waiter, return_exceptions=True)


async def sleep_or_cancel(cancel: asyncio.Event, seconds: float) -> None:
    """Sleep ``seconds``; raise ``AdapterCancelled`` as soon as ``cancel`` is set."""
    try:
        async with asyncio.timeout(max(seconds, 0.0)):
            await cancel.wait()
    except TimeoutError:
        return
    raise AdapterCancelled


def _error_hint(body: bytes) -> str | None:
    try:
        doc = json.loads(body[:65536])
    except ValueError:
        return None
    error = doc.get("error") if isinstance(doc, dict) else None
    candidates: list[object] = [error]
    if isinstance(error, dict):
        candidates = [error.get("code"), error.get("type")]
    for candidate in candidates:
        if isinstance(candidate, str) and _HINT.fullmatch(candidate):
            return candidate
    return None


def raise_for_status(response: HttpResponse) -> None:
    """Map a non-2xx answer to a ``ProviderError``; the body contributes at most a short code."""
    if 200 <= response.status < 300:
        return
    raise classify(response.status, _error_hint(response.body), retry_after=response.retry_after)


def invalid(reason: str) -> ProviderError:
    return ProviderError("provider_invalid_output", reason=reason)


def parse_json_object(body: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(body)
    except ValueError:
        raise invalid("invalid_response") from None
    if not isinstance(doc, dict):
        raise invalid("invalid_response")
    return doc


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise invalid("bad_timestamp")
    return float(value)


def seconds_to_ms(value: object) -> int:
    return round(number(value) * 1000)


def ms_value(value: object) -> int:
    return round(number(value))


def base_url(base: str | None) -> str:
    if not base:
        raise ProviderError("provider_bad_request", reason="base_url_missing")
    return base.rstrip("/")


def safe_model(model: str) -> str:
    """The route's model name, refused when it could break a header, a form or a URL."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}", model) is None:
        raise ProviderError("provider_bad_request", reason="invalid_model")
    return model


def request_language(language: str) -> str:
    """``auto`` or a two-letter code (a region hint such as ``es-CO`` is reduced to ``es``)."""
    value = language.strip()
    if value == AUTO:
        return AUTO
    if re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", value) is None:
        raise ProviderError("provider_bad_request", reason="invalid_language")
    return value[:2]


# --- normalization -------------------------------------------------------------------------------------


def _clamp_span(start: int, end: int, limit: int | None) -> tuple[int, int]:
    start = max(start, 0)
    end = max(end, start)
    if limit is not None and end > limit:
        end = limit
        start = min(start, end)
    return start, end


def build_result(
    *,
    words: Sequence[AsrWord],
    segments: Sequence[AsrSegment],
    has_text: bool,
    language: str,
    audio_ms: int | None,
    diagnostics: Mapping[str, object] | None = None,
) -> AsrResult:
    """Validate provider output into an ``AsrResult`` or raise ``no_word_timestamps``.

    ``audio_ms`` bounds every time (the part duration the caller knows, or the provider's own). A result
    with text but no words, or with a text segment that no word covers, is rejected: times are not
    invented. A result with no text at all (silence) is valid and has no words.
    """
    cleaned: list[AsrWord] = []
    for word in words:
        text = word.text.strip()
        if not text:
            continue
        start, end = _clamp_span(word.start_ms, word.end_ms, audio_ms)
        changed = (start, end) != (word.start_ms, word.end_ms)
        repaired = word.timing_repaired or changed
        cleaned.append(replace(word, text=text, start_ms=start, end_ms=end, timing_repaired=repaired))
    spans: list[AsrSegment] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            start, end = _clamp_span(segment.start_ms, segment.end_ms, audio_ms)
            spans.append(AsrSegment(text, start, end))
    if (has_text or spans) and not cleaned:
        raise ProviderError("no_word_timestamps")
    for segment in spans:
        lo, hi = segment.start_ms - SEGMENT_COVERAGE_SLACK_MS, segment.end_ms + SEGMENT_COVERAGE_SLACK_MS
        if not any(word.end_ms >= lo and word.start_ms <= hi for word in cleaned):
            raise ProviderError("no_word_timestamps")
    return AsrResult(tuple(cleaned), language, tuple(spans), audio_ms, dict(diagnostics or {}))


def _make_monotonic(spans: list[tuple[int, int]], max_overlap_ms: int) -> list[tuple[int, int]]:
    """Clip each span backwards at the start of the next one; never shift anything forwards."""
    out: list[tuple[int, int]] = []
    limit: int | None = None
    for start, end in reversed(spans):
        if limit is not None and end > limit:
            if end - limit > max_overlap_ms:
                raise invalid("overlapping_times")
            end = limit
            start = min(start, end)
        out.append((start, end))
        limit = start
    out.reverse()
    return out


def merge_parts(
    results: Sequence[AsrResult], offsets: Sequence[int], *, max_overlap_ms: int = MAX_OVERLAP_TRIM_MS
) -> AsrResult:
    """Put the parts on the original clock and make word and segment times monotonic.

    ``offsets`` are the ``offset_ms`` of each part from ``audio_prep``. Overlaps of at most
    ``max_overlap_ms`` between neighbours (also across a part boundary) are trimmed by moving the earlier
    item's end back; a larger overlap raises ``provider_invalid_output``. The number of words and
    segments is preserved and no time is moved later. The language is the first part's that has one.
    """
    if not results or len(results) != len(offsets) or any(offset < 0 for offset in offsets):
        raise ValueError("invalid_parts")
    ordered = sorted(zip(offsets, results, strict=True), key=lambda pair: pair[0])
    words: list[AsrWord] = []
    segments: list[AsrSegment] = []
    for offset, result in ordered:
        words.extend(replace(w, start_ms=w.start_ms + offset, end_ms=w.end_ms + offset) for w in result.words)
        segments.extend(replace(s, start_ms=s.start_ms + offset, end_ms=s.end_ms + offset) for s in result.segments)
    word_spans = _make_monotonic([(w.start_ms, w.end_ms) for w in words], max_overlap_ms)
    segment_spans = _make_monotonic([(s.start_ms, s.end_ms) for s in segments], max_overlap_ms)
    merged_words = tuple(
        replace(w, start_ms=s, end_ms=e, timing_repaired=w.timing_repaired or (s, e) != (w.start_ms, w.end_ms))
        for w, (s, e) in zip(words, word_spans, strict=True)
    )
    merged_segments = tuple(
        replace(s, start_ms=start, end_ms=end) for s, (start, end) in zip(segments, segment_spans, strict=True)
    )
    last_offset, last = ordered[-1]
    audio_ms = None if last.audio_ms is None else last_offset + last.audio_ms
    language = next((r.language for _o, r in ordered if r.language not in ("", UNDETERMINED)), UNDETERMINED)
    diagnostics: dict[str, object] = {"parts": len(ordered)}
    deleted = [r.diagnostics["remote_deleted"] for _o, r in ordered if "remote_deleted" in r.diagnostics]
    if deleted:
        diagnostics["remote_deleted"] = all(deleted)
    return AsrResult(merged_words, language, merged_segments, audio_ms, diagnostics)
