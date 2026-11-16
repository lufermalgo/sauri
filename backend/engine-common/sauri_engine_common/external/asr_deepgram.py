"""``deepgram`` transcription transport: ``POST /v1/listen`` with the audio as the request body.

Request
    ``POST {base}/v1/listen?model=<route model>&language=<code>&smart_format=true&punctuate=true&utterances=true``
    (``detect_language=true`` replaces ``language`` for ``auto``), ``Authorization: Token <key>``,
    ``Content-Type`` is the media type of the prepared part (``audio/ogg``), body is the raw audio.
    Word times are always part of the answer (``results.channels[0].alternatives[0].words``, seconds).

Documentation checked 2026-11-16 (developers.deepgram.com: pre-recorded listen reference, pre-recorded audio
guide, supported audio formats, models and languages):
    * Raw upload with ``--data-binary`` and ``Authorization: Token``; maximum file size 2 GB; a request that
      the provider processes for more than 10 minutes (Nova, Base, Enhanced) answers ``504``, which this
      package classifies as ``provider_timeout`` (retryable): long audio is better split by ``audio_prep``.
    * Ogg and Opus are listed as supported; the format is detected from the stream.
    * ``nova-3`` supports Spanish (``es``; ``es-419`` for the monolingual model); ``model`` defaults to
      ``base-general`` when omitted.
    * Word fields are ``word``, ``start``, ``end``, ``confidence`` (and ``punctuated_word`` with
      ``smart_format``, preferred when present; the reference only documents it for utterances).
      The units (seconds) are inferred from the examples, not stated: NO VERIFICADO until U10, as is
      Spanish quality.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

from sauri_engine_common.external.asr_common import (
    AUTO,
    UNDETERMINED,
    AsrResult,
    AsrSegment,
    AsrWord,
    HttpTransport,
    ProviderLimits,
    base_url,
    build_result,
    invalid,
    parse_json_object,
    raise_for_status,
    request_language,
    safe_model,
    seconds_to_ms,
    send,
)
from sauri_engine_common.external.audio_prep import MEDIA_TYPE
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.route import Route
from sauri_engine_common.secrets import SecretRecord

TRANSPORT: Final = "deepgram"
LIMITS: Final = ProviderLimits(max_upload_bytes=2 * 1024**3, max_audio_s=None)


def _probability(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0.0 <= value <= 1.0 else None


def _first(doc: dict[str, Any], *path: str) -> Any:
    node: Any = doc
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def parse_listen(doc: dict[str, Any], *, language: str, audio_ms: int | None) -> AsrResult:
    """Turn a ``/v1/listen`` answer into an ``AsrResult`` (seconds in, milliseconds out)."""
    channels = _first(doc, "results", "channels")
    if not isinstance(channels, list) or not channels or not isinstance(channels[0], dict):
        raise invalid("invalid_response")
    alternatives = channels[0].get("alternatives")
    if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict):
        raise invalid("invalid_response")
    alternative: dict[str, Any] = alternatives[0]
    raw_words = alternative.get("words")
    if raw_words is not None and (not isinstance(raw_words, list) or not all(isinstance(w, dict) for w in raw_words)):
        raise invalid("invalid_response")
    words = [
        AsrWord(
            str(item.get("punctuated_word") or item.get("word") or ""),
            seconds_to_ms(item.get("start")),
            seconds_to_ms(item.get("end")),
            _probability(item.get("confidence")),
        )
        for item in raw_words or []
    ]
    raw_utterances = _first(doc, "results", "utterances")
    if raw_utterances is not None and (
        not isinstance(raw_utterances, list) or not all(isinstance(u, dict) for u in raw_utterances)
    ):
        raise invalid("invalid_response")
    segments = [
        AsrSegment(str(item.get("transcript") or ""), seconds_to_ms(item.get("start")), seconds_to_ms(item.get("end")))
        for item in raw_utterances or []
    ]
    transcript = alternative.get("transcript")
    limit = audio_ms
    duration = _first(doc, "metadata", "duration")
    if limit is None and duration is not None:
        limit = seconds_to_ms(duration)
    detected = channels[0].get("detected_language")
    returned = detected.split("-")[0].lower() if isinstance(detected, str) and detected else UNDETERMINED
    return build_result(
        words=words,
        segments=segments,
        has_text=isinstance(transcript, str) and bool(transcript.strip()),
        language=returned if language == AUTO else language,
        audio_ms=limit,
    )


async def transcribe(
    http: HttpTransport,
    audio: Path,
    *,
    language: str,
    route: Route,
    secret: SecretRecord,
    cancel: asyncio.Event,
    audio_ms: int | None = None,
    allow_local: bool = False,
    media_type: str = MEDIA_TYPE,
) -> AsrResult:
    """Transcribe one prepared part. Times are on the part clock; the caller merges parts with offsets."""
    wanted = request_language(language)
    if not media_type.startswith("audio/") or any(ord(char) < 0x20 or char in " ;\\" for char in media_type):
        raise ProviderError("provider_bad_request", reason="unsupported_media_type")
    query = {"model": safe_model(route.model)}
    if wanted == AUTO:
        query["detect_language"] = "true"
    else:
        query["language"] = wanted
    query.update({"smart_format": "true", "punctuate": "true", "utterances": "true"})
    url = f"{base_url(route.base_url)}/v1/listen?{urlencode(query)}"
    try:
        data = await asyncio.to_thread(audio.read_bytes)
    except OSError:
        raise ProviderError("provider_bad_request", reason="audio_unreadable") from None
    if LIMITS.max_upload_bytes is not None and len(data) > LIMITS.max_upload_bytes:
        raise ProviderError("audio_too_large", reason="over_limit")
    response = await send(
        http,
        "POST",
        url,
        headers={"Authorization": f"Token {secret.key}", "Content-Type": media_type},
        body=data,
        cancel=cancel,
        allow_local=allow_local,
        total_timeout_s=route.timeouts.total_s,
        connect_timeout_s=route.timeouts.connect_s,
    )
    raise_for_status(response)
    return parse_listen(parse_json_object(response.body), language=wanted, audio_ms=audio_ms)
