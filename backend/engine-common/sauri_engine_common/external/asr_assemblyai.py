"""``assemblyai`` transcription transport: upload, create, poll, fetch, delete.

Flow (all calls carry the raw key in ``Authorization``, no scheme prefix)
    1. ``POST {base}/v2/upload`` with the audio bytes (``application/octet-stream``) -> ``upload_url``.
    2. ``POST {base}/v2/transcript`` ``{audio_url, language_code | language_detection, speech_models}``
       -> ``id``. Word timestamps are always part of the finished transcript.
    3. ``GET {base}/v2/transcript/{id}`` with backoff until ``status`` is ``completed`` or ``error``;
       the whole flow is capped (default 1200 s, ``ENGINE_CALL_TIMEOUT_S``).
    4. ``DELETE {base}/v2/transcript/{id}`` in every ending once the id is known (result fetched, provider
       error, timeout, cancellation): data minimization. AssemblyAI deletes the uploaded file with the
       transcript. If the caller cancels before the transcript exists, the upload cannot be deleted
       separately (no such endpoint) and expires on the provider side; if it cancels while the create
       request is in flight, the id is unknown and the job cannot be named.

Documentation checked 2026-11-16 (assemblyai.com/docs: api-reference transcripts submit/get/delete,
files upload, supported languages and file types):
    * ``speech_models`` (array; ``universal-3-5-pro``, ``universal-2``) replaces the deprecated
      ``speech_model``; ``language_code`` and ``language_detection`` are mutually exclusive; Spanish is
      ``es`` on both models; ``words[]`` carry ``text``, ``start``, ``end`` (ms) and ``confidence``.
    * ``DELETE`` returns the transcript with its data removed; the documentation does not say whether it
      works on a job still ``queued``/``processing``: NO VERIFICADO (U10). The error is logged, never
      raised, and ``diagnostics["remote_deleted"]`` tells the caller what happened.
    * ``GET`` is limited to 60 requests per minute per key and transcript: the poll interval grows from
      1 s to at most 5 s. Ogg and Opus are accepted file types. Maximum upload size and duration were not
      found: ``LIMITS`` leaves them ``None`` (NO VERIFICADO, U10), as is Spanish quality.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, TypeVar

from sauri_engine_common.external.asr_common import (
    AUTO,
    UNDETERMINED,
    AsrResult,
    AsrWord,
    HttpResponse,
    HttpTransport,
    ProviderLimits,
    base_url,
    build_result,
    invalid,
    ms_value,
    number,
    parse_json_object,
    raise_for_status,
    request_language,
    safe_model,
    send,
    sleep_or_cancel,
)
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.route import Route
from sauri_engine_common.secrets import SecretRecord

logger = logging.getLogger("sauri.engine_common.asr_assemblyai")
_T = TypeVar("_T")

TRANSPORT: Final = "assemblyai"
LIMITS: Final = ProviderLimits(max_upload_bytes=None, max_audio_s=None)
DEFAULT_DEADLINE_S: Final = 1200.0
POLL_INITIAL_S: Final = 1.0
POLL_MAX_S: Final = 5.0
POLL_BACKOFF: Final = 1.5
MAX_POLL_ERRORS: Final = 3
DELETE_TIMEOUT_S: Final = 10.0

_ID: Final = re.compile(r"[A-Za-z0-9-]{1,64}")
_SERVER_FAULT: Final = ("server error", "internal", "try again")


def _parse_completed(doc: dict[str, Any], *, language: str, audio_ms: int | None) -> AsrResult:
    raw_words = doc.get("words")
    if raw_words is not None and (not isinstance(raw_words, list) or not all(isinstance(w, dict) for w in raw_words)):
        raise invalid("invalid_response")
    words = [
        AsrWord(
            str(item.get("text") or ""),
            ms_value(item.get("start")),
            ms_value(item.get("end")),
            _probability(item.get("confidence")),
        )
        for item in raw_words or []
    ]
    text = doc.get("text")
    limit = audio_ms
    if limit is None and doc.get("audio_duration") is not None:
        limit = (round(number(doc["audio_duration"])) + 1) * 1000  # whole seconds, rounded by the provider
    returned = doc.get("language_code")
    detected = returned.split("_")[0].lower() if isinstance(returned, str) and returned else UNDETERMINED
    return build_result(
        words=words,
        segments=[],
        has_text=isinstance(text, str) and bool(text.strip()),
        language=detected if language == AUTO else language,
        audio_ms=limit,
    )


def _probability(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0.0 <= value <= 1.0 else None


class _Job:
    """Calls of one transcription with a shared deadline, key and cancellation."""

    def __init__(
        self,
        http: HttpTransport,
        route: Route,
        key: str,
        cancel: asyncio.Event,
        allow_local: bool,
        deadline_s: float,
    ) -> None:
        self.http = http
        self.base = base_url(route.base_url)
        self.key = key
        self.cancel = cancel
        self.allow_local = allow_local
        self.route = route
        self.deadline = time.monotonic() + deadline_s
        self.transcript_id: str | None = None

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ProviderError("provider_timeout", reason="deadline")
        return left

    async def call(self, method: str, path: str, body: bytes | None, content_type: str | None) -> HttpResponse:
        headers = {"Authorization": self.key}
        if content_type:
            headers["Content-Type"] = content_type
        response = await send(
            self.http,
            method,
            f"{self.base}{path}",
            headers=headers,
            body=body,
            cancel=self.cancel,
            allow_local=self.allow_local,
            total_timeout_s=min(self.route.timeouts.total_s, self.remaining()),
            connect_timeout_s=self.route.timeouts.connect_s,
        )
        raise_for_status(response)
        return response

    async def create(self, data: bytes, request: dict[str, object]) -> None:
        uploaded = parse_json_object((await self.call("POST", "/v2/upload", data, "application/octet-stream")).body)
        upload_url = uploaded.get("upload_url")
        if not isinstance(upload_url, str) or not upload_url.startswith("https://") or len(upload_url) > 2048:
            raise invalid("invalid_response")
        payload = json.dumps({**request, "audio_url": upload_url}).encode()
        created = parse_json_object((await self.call("POST", "/v2/transcript", payload, "application/json")).body)
        identifier = created.get("id")
        if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
            raise invalid("invalid_response")
        self.transcript_id = identifier

    async def wait_completed(self) -> dict[str, Any]:
        delay = POLL_INITIAL_S
        errors = 0
        while True:
            try:
                polled = await self.call("GET", f"/v2/transcript/{self.transcript_id}", None, None)
                doc = parse_json_object(polled.body)
            except ProviderError as error:
                errors += 1
                if not error.retryable or errors > MAX_POLL_ERRORS:
                    raise
                doc = {}
            else:
                errors = 0
            status = doc.get("status")
            if status == "completed":
                return doc
            if status == "error":
                failure = str(doc.get("error") or "").lower()
                if any(marker in failure for marker in _SERVER_FAULT):
                    raise ProviderError("provider_unavailable", reason="job_failed")
                raise ProviderError("provider_bad_request", reason="job_failed")
            if doc and status not in ("queued", "processing"):
                raise invalid("invalid_status")
            await sleep_or_cancel(self.cancel, min(delay, self.remaining()))
            delay = min(delay * POLL_BACKOFF, POLL_MAX_S)

    async def delete(self) -> bool:
        """Best effort and independent of the cancel event; never raises."""
        if self.transcript_id is None:
            return False
        try:
            response = await self.http.request(
                "DELETE",
                f"{self.base}/v2/transcript/{self.transcript_id}",
                headers={"Authorization": self.key},
                body=None,
                allow_local=self.allow_local,
                total_timeout_s=DELETE_TIMEOUT_S,
                connect_timeout_s=self.route.timeouts.connect_s,
            )
            raise_for_status(response)
        except ProviderError as error:
            logger.warning("assemblyai transcript deletion failed (class=%s)", error.code)
            return False
        except Exception:  # transport faults of an injected transport must not mask the real outcome
            logger.warning("assemblyai transcript deletion failed (class=unexpected)")
            return False
        return True


def language_fields(wanted: str) -> dict[str, object]:
    """Request fields for a language from ``request_language``: a code, or detection for ``auto``."""
    return {"language_detection": True} if wanted == AUTO else {"language_code": wanted}


async def run_transcript_job(
    http: HttpTransport,
    audio: Path,
    *,
    request: dict[str, object],
    parse: Callable[[dict[str, Any]], _T],
    route: Route,
    secret: SecretRecord,
    cancel: asyncio.Event,
    allow_local: bool,
    deadline_s: float,
) -> tuple[_T, bool]:
    """Upload, create, poll and parse one transcript job; also shared with ``diar_assemblyai``.

    ``parse`` receives the finished transcript document. The remote transcript is deleted in every
    ending (the second return value says whether the deletion of the successful job worked).
    """
    try:
        data = await asyncio.to_thread(audio.read_bytes)
    except OSError:
        raise ProviderError("provider_bad_request", reason="audio_unreadable") from None
    job = _Job(http, route, secret.key, cancel, allow_local, deadline_s)
    try:
        await job.create(data, request)
        parsed = parse(await job.wait_completed())
    except BaseException:
        await _cleanup(job)
        raise
    return parsed, await _cleanup(job)


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
    deadline_s: float = DEFAULT_DEADLINE_S,
) -> AsrResult:
    """Transcribe one prepared part; the remote job is deleted whatever the outcome."""
    wanted = request_language(language)
    request: dict[str, object] = {"speech_models": [safe_model(route.model)], **language_fields(wanted)}
    result, deleted = await run_transcript_job(
        http,
        audio,
        request=request,
        parse=lambda doc: _parse_completed(doc, language=wanted, audio_ms=audio_ms),
        route=route,
        secret=secret,
        cancel=cancel,
        allow_local=allow_local,
        deadline_s=deadline_s,
    )
    return AsrResult(result.words, result.language, result.segments, result.audio_ms, {"remote_deleted": deleted})


async def _cleanup(job: _Job) -> bool:
    """Delete the remote transcript even when the surrounding task is being cancelled."""
    task = asyncio.ensure_future(job.delete())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait({task}, timeout=DELETE_TIMEOUT_S)
        raise
