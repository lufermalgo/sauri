"""``assemblyai`` speaker diarization transport: the transcription flow with ``speaker_labels`` on.

The job (upload, create, poll, delete) is the one of ``asr_assemblyai`` (``run_transcript_job``): same
key header, same deadline (default 1200 s), same cancellation and same deletion of the remote transcript
in every ending, so the provider keeps neither the audio nor the transcript. Only the request and the
parsing differ. The provider always returns its transcript text; it is dropped here after reading
whether there was speech, and only ``(label, start, end)`` survives.

Request
    ``POST {base}/v2/transcript`` ``{audio_url, speech_models, language_code | language_detection,
    speaker_labels: true, speakers_expected?}``. ``speakers_expected`` is the exact number of speakers
    ("use only if you are certain"); it is optional and sent only when the caller passes it.

Documentation checked 2026-11-16 (assemblyai.com/docs/speech-to-text/speaker-diarization):
    * ``words[]`` and ``utterances[]`` carry ``speaker`` (letters ``A``, ``B``...), ``start`` and ``end``
      in milliseconds. Words are used; utterances only when the answer has no words.
    * ``speaker_options`` (``min_speakers_expected``, ``max_speakers_expected``) also exists; it is not
      used because the contract here has no such option yet.
    * The page lists no supported languages and no limit on the number of speakers or on audio length, and
      advises about 30 s of uninterrupted speech per speaker for accuracy: Spanish diarization quality and
      limits are NO VERIFICADO (``verified_on = None``, U10). Whether ``null`` speakers occur is not
      documented either: such words are skipped and counted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Final

from sauri_engine_common.external.asr_assemblyai import DEFAULT_DEADLINE_S, language_fields, run_transcript_job
from sauri_engine_common.external.asr_common import (
    HttpTransport,
    ProviderLimits,
    invalid,
    ms_value,
    number,
    request_language,
    safe_model,
)
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.speakers import DiarResult, LabeledWord, build_result, safe_label
from sauri_engine_common.route import Route
from sauri_engine_common.secrets import SecretRecord

TRANSPORT: Final = "assemblyai"
LIMITS: Final = ProviderLimits(max_upload_bytes=None, max_audio_s=None)  # verified_on stays None until U10
# Local sanity bound only; the provider documents no maximum.
MAX_SPEAKERS_EXPECTED: Final = 100


def _timed(items: object) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise invalid("invalid_response")
    return items


def _labeled(items: list[dict[str, Any]]) -> list[LabeledWord]:
    return [
        LabeledWord(safe_label(item.get("speaker")), ms_value(item.get("start")), ms_value(item.get("end")))
        for item in items
    ]


def parse_completed(doc: dict[str, Any], *, audio_ms: int | None) -> DiarResult:
    """Turn a finished transcript into a ``DiarResult``; the provider text never leaves this function."""
    words = _labeled(_timed(doc.get("words")))
    spans = _labeled(_timed(doc.get("utterances"))) if not words else []
    text = doc.get("text")
    has_speech = bool(words or spans) or (isinstance(text, str) and bool(text.strip()))
    del text  # the provider's text is not kept
    limit = audio_ms
    if limit is None and doc.get("audio_duration") is not None:
        limit = (round(number(doc["audio_duration"])) + 1) * 1000  # whole seconds, rounded by the provider
    return build_result(words or spans, has_speech=has_speech, audio_ms=limit)


async def diarize(
    http: HttpTransport,
    audio: Path,
    *,
    route: Route,
    secret: SecretRecord,
    cancel: asyncio.Event,
    language: str = "auto",
    speakers_expected: int | None = None,
    audio_ms: int | None = None,
    allow_local: bool = False,
    deadline_s: float = DEFAULT_DEADLINE_S,
) -> DiarResult:
    """Label the speakers of one prepared part. Times are on the part clock; the caller merges parts."""
    wanted = request_language(language)
    request: dict[str, object] = {
        "speech_models": [safe_model(route.model)],
        **language_fields(wanted),
        "speaker_labels": True,
    }
    if speakers_expected is not None:
        if isinstance(speakers_expected, bool) or not 1 <= speakers_expected <= MAX_SPEAKERS_EXPECTED:
            raise ProviderError("provider_bad_request", reason="invalid_speakers_expected")
        request["speakers_expected"] = speakers_expected
    result, deleted = await run_transcript_job(
        http,
        audio,
        request=request,
        parse=lambda doc: parse_completed(doc, audio_ms=audio_ms),
        route=route,
        secret=secret,
        cancel=cancel,
        allow_local=allow_local,
        deadline_s=deadline_s,
    )
    return DiarResult(
        result.segments, result.speaker_count, result.audio_ms, {**result.diagnostics, "remote_deleted": deleted}
    )
