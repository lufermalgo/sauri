"""``deepgram`` speaker diarization transport: ``POST /v1/listen`` with diarization on.

Request
    ``POST {base}/v1/listen?model=<route model>&diarize_model=<latest>&language=<code>``
    (``detect_language=true`` replaces ``language`` for ``auto``), ``Authorization: Token <key>``,
    ``Content-Type`` is the media type of the prepared part (``audio/ogg``), body is the raw audio.
    The answer is read from ``results.channels[0].alternatives[0].words``: ``start`` and ``end`` (seconds,
    as in ``asr_deepgram``) and ``speaker`` (integer). The transcript text is not requested to be
    formatted and is dropped; only ``(speaker, start, end)`` survives.

Documentation checked 2026-11-16 (developers.deepgram.com/docs/diarization):
    * ``diarize_model`` (``latest``, currently ``v2``, ``v2`` or ``v1`` for pre-recorded audio) turns
      diarization on by itself. ``diarize=true`` is deprecated (always routes to v1) and a request that
      sets both is rejected, so only ``diarize_model`` is sent. This deviates from the plain
      ``diarize=true`` of the task text on purpose.
    * Supported models: Nova-1, Nova-2, Nova-3, enhanced and base (not Whisper). ``speaker_confidence``
      exists for pre-recorded audio and is ignored.
    * A self-hosted deployment at release 260514 or later answers ``diarize=true`` without speaker labels;
      an answer with words but no ``speaker`` at all is rejected here (``no_speaker_labels``).
    * The page does not state units, languages with diarization, or limits. Seconds are inferred from the
      examples (as in ``asr_deepgram``); Spanish diarization quality and size limits are NO VERIFICADO
      (``verified_on = None``, U10). The 2 GB file size limit and the 10 minute processing cap come from
      the transcription pages (``asr_deepgram``) and are reused.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

from sauri_engine_common.external.asr_common import (
    AUTO,
    HttpTransport,
    ProviderLimits,
    base_url,
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
from sauri_engine_common.external.speakers import DiarResult, LabeledWord, build_result, safe_label
from sauri_engine_common.route import Route
from sauri_engine_common.secrets import SecretRecord

TRANSPORT: Final = "deepgram"
LIMITS: Final = ProviderLimits(max_upload_bytes=2 * 1024**3, max_audio_s=None)  # verified_on stays None until U10
DIARIZE_MODEL: Final = "latest"

_DIARIZE_MODEL: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")


def _first(doc: dict[str, Any], *path: str) -> Any:
    node: Any = doc
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def parse_listen(doc: dict[str, Any], *, audio_ms: int | None) -> DiarResult:
    """Turn a ``/v1/listen`` answer into a ``DiarResult``; the provider text never leaves this function."""
    channels = _first(doc, "results", "channels")
    if not isinstance(channels, list) or not channels or not isinstance(channels[0], dict):
        raise invalid("invalid_response")
    alternatives = channels[0].get("alternatives")
    if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict):
        raise invalid("invalid_response")
    raw_words = alternatives[0].get("words")
    if raw_words is not None and (not isinstance(raw_words, list) or not all(isinstance(w, dict) for w in raw_words)):
        raise invalid("invalid_response")
    words = [
        LabeledWord(safe_label(item.get("speaker")), seconds_to_ms(item.get("start")), seconds_to_ms(item.get("end")))
        for item in raw_words or []
    ]
    transcript = alternatives[0].get("transcript")
    has_speech = bool(words) or (isinstance(transcript, str) and bool(transcript.strip()))
    if has_speech and not words:
        raise ProviderError("no_word_timestamps")  # speech with no word times: nothing to attribute
    del transcript  # the provider's text is not kept
    limit = audio_ms
    duration = _first(doc, "metadata", "duration")
    if limit is None and duration is not None:
        limit = seconds_to_ms(duration)
    return build_result(words, has_speech=has_speech, audio_ms=limit)


async def diarize(
    http: HttpTransport,
    audio: Path,
    *,
    route: Route,
    secret: SecretRecord,
    cancel: asyncio.Event,
    language: str = AUTO,
    audio_ms: int | None = None,
    allow_local: bool = False,
    media_type: str = MEDIA_TYPE,
    diarize_model: str = DIARIZE_MODEL,
) -> DiarResult:
    """Label the speakers of one prepared part. Times are on the part clock; the caller merges parts."""
    wanted = request_language(language)
    if not media_type.startswith("audio/") or any(ord(char) < 0x20 or char in " ;\\" for char in media_type):
        raise ProviderError("provider_bad_request", reason="unsupported_media_type")
    if _DIARIZE_MODEL.fullmatch(diarize_model) is None:
        raise ProviderError("provider_bad_request", reason="invalid_diarize_model")
    query = {"model": safe_model(route.model), "diarize_model": diarize_model}
    if wanted == AUTO:
        query["detect_language"] = "true"
    else:
        query["language"] = wanted
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
    return parse_listen(parse_json_object(response.body), audio_ms=audio_ms)
