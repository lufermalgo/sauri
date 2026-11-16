"""External transcription routes of the ASR gateway (``X-Sauri-Route`` with a provider kind).

The worker resolves the route from PostgreSQL and the consent; this module only executes it:

1. ``load_secret`` re-validates the route against the gateway's own matrix (consent version present,
   HTTPS unless loopback, key bound to the route's origin) and reads the key from the host secret store.
   The key is read after every check that does not need it, and no network call happens before all pass.
2. ``transcribe_external`` compresses the already normalized WAV, splits it at voice pauses when the
   provider has an upload limit, calls the adapter once per part and merges the parts on the original
   clock (``merge_parts`` is the only place that applies offsets).
3. The answer keeps the v2 body of the local engine; ``segments_from_words`` builds segments for providers
   that return none (AssemblyAI), using only the provider's own words and times.

Nothing here logs or stores a key, a provider body, a transcript or an audio path. Failures are
``ProviderError`` values (closed class codes) or ``AdapterCancelled``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sauri_engine_common.external import asr_assemblyai, asr_deepgram, asr_openai_audio
from sauri_engine_common.external.asr_common import (
    UNDETERMINED,
    AdapterCancelled,
    AsrResult,
    AsrSegment,
    AsrWord,
    HttpTransport,
    ProviderLimits,
    merge_parts,
)
from sauri_engine_common.external.audio_prep import VadFn, prepare_audio
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.route import LOCAL_KIND, Route, RouteError, decode_route, validate_route
from sauri_engine_common.secrets import SecretRecord, SecretStore, SecretUnavailableError, default_secret_store

# Word-level JSON of an hour of speech weighs a few MiB; the provider-call default (2 MiB) would cut it.
MAX_PROVIDER_RESPONSE_BYTES: Final = 32 * 1024 * 1024
# (kind, transport) pairs served for transcription; each needs a key. Same rows as the API matrix.
SUPPORTED: Final[frozenset[tuple[str, str]]] = frozenset(
    {("assemblyai", "assemblyai"), ("deepgram", "deepgram"), ("groq", "openai-audio")}
)
WATCH_INTERVAL_S: Final = 1.0
# Segment rules for providers without segments: a sentence end, a long pause or a size cap closes one.
SEGMENT_GAP_MS: Final = 1500
SEGMENT_MAX_MS: Final = 30_000
SEGMENT_MAX_WORDS: Final = 80
_SENTENCE_END: Final = (".", "?", "!", "…")

_HTTP_STATUS: Final[dict[str, int]] = {
    "provider_auth": 502,
    "provider_quota": 502,
    "provider_rate_limited": 429,
    "provider_timeout": 504,
    "provider_unavailable": 502,
    "provider_bad_request": 502,
    "provider_invalid_output": 502,
    "provider_context_exceeded": 502,
    "provider_unsupported": 422,
    "audio_too_large": 413,
    "no_word_timestamps": 502,
    "consent_missing": 422,
    "origin_mismatch": 422,
    "secret_unavailable": 503,
}


def error_status(error: ProviderError) -> int:
    """HTTP status of a classified failure (the worker reads the body; the status is for people and logs)."""
    if isinstance(error, RouteError):
        return 422  # the request itself was malformed: no provider was involved
    return _HTTP_STATUS.get(error.code, 502)


class GatewayMatrix:
    """Pairs this gateway serves: the transcription rows of ``app.engines.capability_matrix``."""

    def supports(self, kind: str, capability: str, transport: str) -> bool:
        return capability == "transcription" and (kind, transport) in SUPPORTED


def external_route(header: str | None) -> Route | None:
    """The decoded route when it names an external provider; ``None`` for no header or a local route.

    Raises ``RouteError`` for a malformed header (the gateway answers 422 with its reason code).
    """
    route = decode_route(header)
    if route is None or route.kind == LOCAL_KIND:
        return None
    return route


def load_secret(route: Route, store: SecretStore | None = None) -> SecretRecord:
    """Validate ``route`` and read its key. Blocking (the Keychain is a subprocess): run in a thread."""
    matrix = GatewayMatrix()
    try:
        # Everything that needs no key first: a refused route never touches the secret store.
        validate_route(route, matrix, None)
    except ProviderError as error:
        if error.code != "secret_unavailable" or route.secret_ref is None:
            raise
    if route.secret_ref is None:
        raise ProviderError("secret_unavailable", reason="key_required")
    try:
        record = (store or default_secret_store()).get(route.secret_ref)
    except SecretUnavailableError:
        raise ProviderError("secret_unavailable") from None
    except Exception:  # any other store failure is reported by class, never by content
        raise ProviderError("secret_unavailable") from None
    validate_route(route, matrix, record)
    return record


def segments_from_words(words: Sequence[AsrWord]) -> tuple[AsrSegment, ...]:
    """Group words into segments with the provider's own words and times (nothing is invented)."""
    segments: list[AsrSegment] = []
    current: list[AsrWord] = []

    def close() -> None:
        if current:
            text = " ".join(word.text for word in current)
            segments.append(AsrSegment(text, current[0].start_ms, current[-1].end_ms))
            current.clear()

    for word in words:
        if current and (
            word.start_ms - current[-1].end_ms >= SEGMENT_GAP_MS
            or word.end_ms - current[0].start_ms > SEGMENT_MAX_MS
            or len(current) >= SEGMENT_MAX_WORDS
        ):
            close()
        current.append(word)
        if word.text.endswith(_SENTENCE_END):
            close()
    close()
    return tuple(segments)


@dataclass(frozen=True)
class ExternalOutcome:
    result: AsrResult
    segments: tuple[AsrSegment, ...]
    audio_ms: int
    parts: int
    dropped_ms: int
    bitrate_bps: int
    prepare_ms: int
    provider_ms: int


PartCall = Callable[..., Awaitable[AsrResult]]


def _openai_audio(http: HttpTransport, part: Path, **kw: Any) -> Awaitable[AsrResult]:
    kw.pop("deadline_s", None)
    return asr_openai_audio.transcribe(http, part, **kw)


def _deepgram(http: HttpTransport, part: Path, **kw: Any) -> Awaitable[AsrResult]:
    kw.pop("deadline_s", None)
    return asr_deepgram.transcribe(http, part, **kw)


def _assemblyai(http: HttpTransport, part: Path, **kw: Any) -> Awaitable[AsrResult]:
    kw.pop("media_type", None)
    return asr_assemblyai.transcribe(http, part, **kw)


_TRANSPORTS: Final[dict[str, tuple[ProviderLimits, PartCall]]] = {
    "openai-audio": (asr_openai_audio.LIMITS, _openai_audio),
    "deepgram": (asr_deepgram.LIMITS, _deepgram),
    "assemblyai": (asr_assemblyai.LIMITS, _assemblyai),
}


async def transcribe_external(
    *,
    http: HttpTransport,
    route: Route,
    secret: SecretRecord,
    wav: Path,
    language: str,
    cancel: asyncio.Event,
    deadline_s: float,
    allow_local: bool = False,
    vad: VadFn | None = None,
) -> ExternalOutcome:
    """Transcribe the normalized ``wav`` with the route's provider and return the merged result.

    ``deadline_s`` bounds preparation and every provider call; it is never above the route's own ceiling.
    Cancelling ``cancel`` aborts the open provider request and deletes remote jobs (adapter contract).
    """
    entry = _TRANSPORTS.get(route.transport or "")
    if entry is None:
        raise ProviderError("provider_unsupported")
    limits, call = entry
    budget = min(deadline_s, route.timeouts.total_s)
    started = time.monotonic()
    stack = contextlib.ExitStack()
    try:
        async with asyncio.timeout(budget):
            prepared = await asyncio.to_thread(
                lambda: stack.enter_context(
                    prepare_audio(
                        wav,
                        max_bytes=limits.max_upload_bytes,
                        max_seconds=limits.max_audio_s,
                        vad=vad,
                        workdir=wav.parent,
                        timeout_s=min(300.0, budget),
                    )
                )
            )
            prepare_ms = round((time.monotonic() - started) * 1000)
            results: list[AsrResult] = []
            for part in prepared.parts:
                if cancel.is_set():
                    raise AdapterCancelled
                results.append(
                    await call(
                        http,
                        part.path,
                        language=language,
                        route=route,
                        secret=secret,
                        cancel=cancel,
                        audio_ms=part.duration_ms,
                        allow_local=allow_local,
                        media_type=prepared.media_type,
                        deadline_s=max(budget - (time.monotonic() - started), 1.0),
                    )
                )
            merged = merge_parts(results, [part.offset_ms for part in prepared.parts])
    except TimeoutError:
        raise ProviderError("provider_timeout", reason="deadline") from None
    finally:
        await asyncio.to_thread(stack.close)
    provider_ms = round((time.monotonic() - started) * 1000) - prepare_ms
    if merged.language == UNDETERMINED:
        if language == "auto":
            raise ProviderError("provider_invalid_output", reason="language_undetermined")
        merged = AsrResult(merged.words, language, merged.segments, merged.audio_ms, merged.diagnostics)
    segments = merged.segments or segments_from_words(merged.words)
    return ExternalOutcome(
        result=merged,
        segments=segments,
        audio_ms=prepared.source_ms,
        parts=len(prepared.parts),
        dropped_ms=prepared.dropped_ms,
        bitrate_bps=prepared.bitrate_bps,
        prepare_ms=prepare_ms,
        provider_ms=provider_ms,
    )


async def watch_disconnect(
    is_disconnected: Callable[[], Awaitable[bool]], cancel: asyncio.Event, interval_s: float = WATCH_INTERVAL_S
) -> None:
    """Set ``cancel`` when the client (the worker) goes away: FastAPI does not cancel the handler itself."""
    while not cancel.is_set():
        if await is_disconnected():
            cancel.set()
            return
        await asyncio.sleep(interval_s)


def allow_local_providers() -> bool:
    """Loopback provider addresses are refused unless a test or a local-app setup opts in."""
    return os.environ.get("SAURI_ASR_ALLOW_LOCAL_PROVIDERS") == "1"

