"""``openai-audio`` transcription transport: Groq and OpenAI-compatible audio servers.

Request (``POST {base_url}/audio/transcriptions``, ``multipart/form-data``)
    ``file``, ``model`` (from the route), ``response_format=verbose_json``,
    ``timestamp_granularities[]=word`` and ``timestamp_granularities[]=segment``, and ``language``
    (omitted for ``auto``). ``Authorization: Bearer <key>``.

Documentation checked 2026-11-16 (console.groq.com/docs/speech-to-text, console.groq.com/docs/api-reference,
developers.openai.com audio transcription reference):
    * Groq models ``whisper-large-v3`` and ``whisper-large-v3-turbo``; formats flac, mp3, mp4, mpeg, mpga,
      m4a, ogg, wav, webm; direct upload up to 25 MB (free tier; 100 MB on the dev tier only through the
      ``url`` parameter, which this adapter does not use); ``timestamp_granularities[]`` needs
      ``verbose_json`` and adds latency; ``language`` is ISO-639-1; billing minimum of 10 s per request.
    * The Groq pages do not show the ``verbose_json`` body. The shape parsed here (``words[]`` with
      ``word``/``start``/``end`` in seconds, ``segments[]``, ``duration``, ``language``) is the OpenAI one
      and is NO VERIFICADO against a real Groq answer, nor is the claim that both Groq models return word
      times (U10).
    * OpenAI proper: only ``whisper-1`` accepts word timestamps (the other models answer ``json`` only);
      OpenAI is out of the transcription matrix of this spec, the adapter is kept generic.
    * Spanish quality and the real limits are NO VERIFICADO until U10 (``LIMITS.verified_on`` is ``None``).
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Final

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

TRANSPORT: Final = "openai-audio"
LIMITS: Final = ProviderLimits(max_upload_bytes=25 * 1024 * 1024, max_audio_s=None)

_EXTENSIONS: Final = {
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
}

# Whisper reports the language as an English name; the contract carries the ISO-639-1 code.
_LANGUAGE_CODES: Final = {
    name: code
    for code, name in (
        ("en", "english"),
        ("zh", "chinese"),
        ("de", "german"),
        ("es", "spanish"),
        ("ru", "russian"),
        ("ko", "korean"),
        ("fr", "french"),
        ("ja", "japanese"),
        ("pt", "portuguese"),
        ("tr", "turkish"),
        ("pl", "polish"),
        ("ca", "catalan"),
        ("nl", "dutch"),
        ("ar", "arabic"),
        ("sv", "swedish"),
        ("it", "italian"),
        ("id", "indonesian"),
        ("hi", "hindi"),
        ("fi", "finnish"),
        ("vi", "vietnamese"),
        ("he", "hebrew"),
        ("uk", "ukrainian"),
        ("el", "greek"),
        ("ms", "malay"),
        ("cs", "czech"),
        ("ro", "romanian"),
        ("da", "danish"),
        ("hu", "hungarian"),
        ("ta", "tamil"),
        ("no", "norwegian"),
        ("th", "thai"),
        ("ur", "urdu"),
        ("hr", "croatian"),
        ("bg", "bulgarian"),
        ("lt", "lithuanian"),
        ("la", "latin"),
        ("mi", "maori"),
        ("ml", "malayalam"),
        ("cy", "welsh"),
        ("sk", "slovak"),
        ("te", "telugu"),
        ("fa", "persian"),
        ("lv", "latvian"),
        ("bn", "bengali"),
        ("sr", "serbian"),
        ("az", "azerbaijani"),
        ("sl", "slovenian"),
        ("kn", "kannada"),
        ("et", "estonian"),
        ("mk", "macedonian"),
        ("br", "breton"),
        ("eu", "basque"),
        ("is", "icelandic"),
        ("hy", "armenian"),
        ("ne", "nepali"),
        ("mn", "mongolian"),
        ("bs", "bosnian"),
        ("kk", "kazakh"),
        ("sq", "albanian"),
        ("sw", "swahili"),
        ("gl", "galician"),
        ("mr", "marathi"),
        ("pa", "punjabi"),
        ("si", "sinhala"),
        ("km", "khmer"),
        ("sn", "shona"),
        ("yo", "yoruba"),
        ("so", "somali"),
        ("af", "afrikaans"),
        ("oc", "occitan"),
        ("ka", "georgian"),
        ("be", "belarusian"),
        ("tg", "tajik"),
        ("sd", "sindhi"),
        ("gu", "gujarati"),
        ("am", "amharic"),
        ("yi", "yiddish"),
        ("lo", "lao"),
        ("uz", "uzbek"),
        ("fo", "faroese"),
        ("ht", "haitian creole"),
        ("ps", "pashto"),
        ("tk", "turkmen"),
        ("nn", "nynorsk"),
        ("mt", "maltese"),
        ("sa", "sanskrit"),
        ("lb", "luxembourgish"),
        ("my", "myanmar"),
        ("bo", "tibetan"),
        ("tl", "tagalog"),
        ("mg", "malagasy"),
        ("as", "assamese"),
        ("tt", "tatar"),
        ("haw", "hawaiian"),
        ("ln", "lingala"),
        ("ha", "hausa"),
        ("ba", "bashkir"),
        ("jw", "javanese"),
        ("su", "sundanese"),
    )
}


def _multipart(fields: list[tuple[str, str]], filename: str, content_type: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"sauri-{secrets.token_hex(16)}"
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    parts.append(data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _detected_language(raw: object, requested: str) -> str:
    if requested != AUTO:
        return requested
    if isinstance(raw, str):
        name = raw.strip().lower()
        if name in _LANGUAGE_CODES:
            return _LANGUAGE_CODES[name]
        if len(name) == 2 and name.isalpha():
            return name
    return UNDETERMINED


def _items(doc: dict[str, object], name: str) -> list[dict[str, object]]:
    raw = doc.get(name)
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise invalid("invalid_response")
    return [item for item in raw if isinstance(item, dict)]


def parse_verbose_json(doc: dict[str, object], *, language: str, audio_ms: int | None) -> AsrResult:
    """Turn a ``verbose_json`` answer into an ``AsrResult`` (times in seconds in, milliseconds out)."""
    words = [
        AsrWord(str(item.get("word") or ""), seconds_to_ms(item.get("start")), seconds_to_ms(item.get("end")))
        for item in _items(doc, "words")
    ]
    segments = [
        AsrSegment(str(item.get("text") or ""), seconds_to_ms(item.get("start")), seconds_to_ms(item.get("end")))
        for item in _items(doc, "segments")
    ]
    text = doc.get("text")
    has_text = isinstance(text, str) and bool(text.strip())
    limit = audio_ms
    if limit is None and doc.get("duration") is not None:
        limit = seconds_to_ms(doc["duration"])
    return build_result(
        words=words,
        segments=segments,
        has_text=has_text,
        language=_detected_language(doc.get("language"), language),
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
    extension = _EXTENSIONS.get(media_type)
    if extension is None:
        raise ProviderError("provider_bad_request", reason="unsupported_media_type")
    url = f"{base_url(route.base_url)}/audio/transcriptions"
    try:
        data = await asyncio.to_thread(audio.read_bytes)
    except OSError:
        raise ProviderError("provider_bad_request", reason="audio_unreadable") from None
    if LIMITS.max_upload_bytes is not None and len(data) > LIMITS.max_upload_bytes:
        raise ProviderError("audio_too_large", reason="over_limit")
    fields = [
        ("model", safe_model(route.model)),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("timestamp_granularities[]", "segment"),
    ]
    if wanted != AUTO:
        fields.append(("language", wanted))
    body, content_type = _multipart(fields, f"audio.{extension}", media_type, data)
    response = await send(
        http,
        "POST",
        url,
        headers={"Authorization": f"Bearer {secret.key}", "Content-Type": content_type},
        body=body,
        cancel=cancel,
        allow_local=allow_local,
        total_timeout_s=route.timeouts.total_s,
        connect_timeout_s=route.timeouts.connect_s,
    )
    raise_for_status(response)
    return parse_verbose_json(parse_json_object(response.body), language=wanted, audio_ms=audio_ms)
