"""External speaker routes of the diarization gateway (``X-Sauri-Route`` with a provider kind).

The worker resolves the route from PostgreSQL and the consent; this module only executes it, exactly as
``asr-engine/asr_external.py`` does for transcription:

1. ``load_secret`` re-validates the route against the gateway's own matrix (diarization rows only, consent
   version present, HTTPS unless loopback, key bound to the route's origin) and reads the key from the host
   secret store. The key is read after every check that does not need it; nothing goes out before all pass.
2. ``diarize_external`` compresses the already normalized WAV, splits it when the provider has an upload
   limit, calls the adapter once per part and merges the parts on the original clock (``merge_parts`` is the
   only place that applies offsets).
3. The answer keeps the v2 body of the local Senko engine. Segments with no duration are dropped and counted,
   as the local engine does, so every consumer sees the same contract.

Per-part labels stay distinct (``p1.A``, ``p2.A``) because provider labels are local to one job: a merged
``speaker_count`` can therefore over-count real people when the audio was split. The diagnostics say so
(``label_policy``, ``speaker_count_per_part``); nothing is guessed.

Nothing here logs or stores a key, a provider body, a transcript or an audio path. Failures are
``ProviderError`` values (closed class codes) or ``AdapterCancelled``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sauri_engine_common.external import diar_assemblyai, diar_deepgram
from sauri_engine_common.external.asr_common import AdapterCancelled, HttpTransport, ProviderLimits
from sauri_engine_common.external.audio_prep import prepare_audio
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.speakers import DiarResult, merge_parts
from sauri_engine_common.route import LOCAL_KIND, Route, RouteError, decode_route, validate_route
from sauri_engine_common.secrets import SecretRecord, SecretStore, SecretUnavailableError, default_secret_store

# Word-level JSON of an hour of speech weighs a few MiB; the provider-call default (2 MiB) would cut it.
MAX_PROVIDER_RESPONSE_BYTES: Final = 32 * 1024 * 1024
# (kind, transport) pairs served for diarization; each needs a key. Same rows as the API matrix.
SUPPORTED: Final[frozenset[tuple[str, str]]] = frozenset({("assemblyai", "assemblyai"), ("deepgram", "deepgram")})
WATCH_INTERVAL_S: Final = 1.0
# Ceiling of one external run (download and normalization included); the route's own total is never exceeded.
EXTERNAL_BUDGET_S: Final = 3600.0

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
    """Pairs this gateway serves: the diarization rows of ``app.engines.capability_matrix``."""

    def supports(self, kind: str, capability: str, transport: str) -> bool:
        return capability == "diarization" and (kind, transport) in SUPPORTED


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


PartCall = Callable[..., Awaitable[DiarResult]]


def _assemblyai(http: HttpTransport, part: Path, **kw: Any) -> Awaitable[DiarResult]:
    kw.pop("media_type", None)
    return diar_assemblyai.diarize(http, part, **kw)


def _deepgram(http: HttpTransport, part: Path, **kw: Any) -> Awaitable[DiarResult]:
    kw.pop("deadline_s", None)
    return diar_deepgram.diarize(http, part, **kw)


_TRANSPORTS: Final[dict[str, tuple[ProviderLimits, PartCall]]] = {
    "assemblyai": (diar_assemblyai.LIMITS, _assemblyai),
    "deepgram": (diar_deepgram.LIMITS, _deepgram),
}


@dataclass(frozen=True)
class ExternalOutcome:
    result: DiarResult
    audio_ms: int
    parts: int
    dropped_ms: int
    bitrate_bps: int
    prepare_ms: int
    provider_ms: int


async def diarize_external(
    *,
    http: HttpTransport,
    route: Route,
    secret: SecretRecord,
    wav: Path,
    cancel: asyncio.Event,
    deadline_s: float,
    allow_local: bool = False,
) -> ExternalOutcome:
    """Label the speakers of the normalized ``wav`` with the route's provider and return the merged result.

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
            # Without a VAD callable a part is split by hard cuts only; the gateway has no speech detector
            # of its own, and the providers served here have no upload limit that would need one in practice.
            prepared = await asyncio.to_thread(
                lambda: stack.enter_context(
                    prepare_audio(
                        wav,
                        max_bytes=limits.max_upload_bytes,
                        max_seconds=limits.max_audio_s,
                        vad=None,
                        workdir=wav.parent,
                        timeout_s=min(300.0, budget),
                    )
                )
            )
            prepare_ms = round((time.monotonic() - started) * 1000)
            results: list[DiarResult] = []
            for part in prepared.parts:
                if cancel.is_set():
                    raise AdapterCancelled
                results.append(
                    await call(
                        http,
                        part.path,
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
    return ExternalOutcome(
        result=merged,
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
    return os.environ.get("SAURI_DIAR_ALLOW_LOCAL_PROVIDERS") == "1"
