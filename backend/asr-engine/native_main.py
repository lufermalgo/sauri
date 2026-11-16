"""Host-native ASR service using whisper.cpp on Metal."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import asr_external
import boto3
from asr_assets import vad_cli_path, vad_model_path, verify_assets
from asr_config import (
    chunk_ms,
    default_language,
    default_prompt_enabled,
    language_code,
    remaining,
    server_budget,
    suppress_nst,
    vad_enabled,
    vad_threshold,
)
from asr_diagnostics import diagnostic_tail
from asr_prompt import DEFAULT_PROMPT, DEFAULT_PROMPT_LANGUAGE, vocabulary_prompt
from asr_vad import align_chunks, cut_wav, group_chunks, parse_vad
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sauri_engine_common.audio import NormalizeError, normalize_to_wav
from sauri_engine_common.credentials import object_store_credentials
from sauri_engine_common.external.asr_common import AdapterCancelled
from sauri_engine_common.external.audio_prep import vad_cli_runner
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.keep_awake import KeepAwake, KeepAwakeError
from sauri_engine_common.local_model_use import LocalModelError, LocalSelection, select_local_model
from sauri_engine_common.route import ROUTE_HEADER, Route, RouteError
from sauri_engine_common.secrets import SecretStore
from whisper_words import NoSpeechError, NoWordTimestampsError, WordsResult, words_from_ggml_json

logger = logging.getLogger("asr-engine-native")
logging.basicConfig(level=logging.INFO)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
MINIO_AUDIO_PREFIX = os.environ.get("MINIO_AUDIO_PREFIX", "recordings/")
ENGINE_TOKEN_PATH = Path(
    os.environ.get("SAURI_ENGINE_TOKEN_FILE", Path.home() / ".config" / "sauri" / "engine_token")
)
RECORDING_CAPABILITY_KEY_PATH = Path(
    os.environ.get(
        "SAURI_RECORDING_CAPABILITY_KEY_FILE",
        Path.home() / ".config" / "sauri" / "recording_capability_key",
    )
)
RECORDING_CAPABILITY_TTL_SECONDS = 60
MODEL_ID = "ggml-large-v3-turbo-q5_0"
MODEL_DEVICE = "metal"
WHISPER_CLI = os.environ.get("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")
ASR_MODEL_PATH = Path(os.environ.get(
    "ASR_MODEL_PATH", "~/.local/share/sauri/models/ggml-large-v3-turbo-q5_0.bin",
)).expanduser()
ASR_THREADS = int(os.environ.get("ASR_THREADS", "4"))
_job_lock = threading.Lock()
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)

s3_client: Any = None
# Host secret store for provider keys; None means the default store (Keychain, else private files).
secret_store: SecretStore | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Check local inference assets and initialize object storage."""
    global s3_client
    default_language()
    server_budget()
    suppress_nst()
    default_prompt_enabled()
    if vad_enabled():
        vad_threshold()
        chunk_ms()
    try:
        verify_assets(ASR_MODEL_PATH, Path(WHISPER_CLI))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Native ASR asset verification failed") from exc
    access_key, secret_key = object_store_credentials()
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", connect_timeout=min(5, server_budget() / 100),
                      read_timeout=min(5, server_budget() / 100),
                      retries={"max_attempts": 0}),
    )
    logger.info("Native ASR initialized (model=%s)", MODEL_ID)
    yield
    s3_client = None


app = FastAPI(title="Sauri Native ASR Engine", version="1.0.0", lifespan=lifespan)


class TranscribeRequest(BaseModel):
    audio_ref: str
    language: str = Field(default_factory=default_language)
    contract_version: Literal[2] = 2

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: object) -> str:
        try:
            if not isinstance(value, str):
                raise ValueError("invalid_language")
            return language_code(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_language") from exc


class Segment(BaseModel):
    text: str
    start_ms: int
    end_ms: int


class Word(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None
    timing_repaired: bool = False


class EngineInfo(BaseModel):
    name: str
    model: str
    device: str


class TranscribeResponse(BaseModel):
    contract_version: Literal[2] = 2
    segments: list[Segment]
    words: list[Word]
    language: str
    engine: EngineInfo
    diagnostics: dict[str, object]


def _require_engine_token(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        expected = ENGINE_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Engine authentication unavailable") from exc
    if not expected:
        raise HTTPException(status_code=503, detail="Engine authentication unavailable")
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _validate_audio_ref(audio_ref: str) -> None:
    parts = audio_ref.split("/")
    if (
        not MINIO_AUDIO_PREFIX.endswith("/")
        or not audio_ref.startswith(MINIO_AUDIO_PREFIX)
        or audio_ref.startswith("/")
        or "\\" in audio_ref
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise HTTPException(status_code=400, detail="Invalid audio reference")


def _require_recording_capability(audio_ref: str, capability: str | None) -> None:
    if capability is None:
        raise HTTPException(status_code=403, detail="Recording authorization required")
    try:
        secret = RECORDING_CAPABILITY_KEY_PATH.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Recording authorization unavailable") from exc
    if not secret:
        raise HTTPException(status_code=503, detail="Recording authorization unavailable")
    try:
        expiry_text, signature = capability.split(".", maxsplit=1)
        expires_at = int(expiry_text)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="Invalid recording authorization") from exc
    now = int(time.time())
    if expires_at <= now or expires_at > now + RECORDING_CAPABILITY_TTL_SECONDS:
        raise HTTPException(status_code=403, detail="Expired recording authorization")
    message = f"{audio_ref}\n{expires_at}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid recording authorization")


def _download_audio(audio_ref: str, deadline: float) -> str:
    if s3_client is None:
        raise RuntimeError("Object store is not initialized")
    suffix = Path(audio_ref).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        audio_path = temp.name
    try:
        remaining(deadline)
        body = s3_client.get_object(Bucket=MINIO_BUCKET, Key=audio_ref)["Body"]
        try:
            with open(audio_path, "wb") as output:
                while True:
                    # The client's read_timeout bounds each read; this bounds the whole download.
                    remaining(deadline)
                    chunk = body.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
        finally:
            body.close()
    except Exception as exc:
        with suppress(OSError):
            os.unlink(audio_path)
        raise RuntimeError("Audio download failed") from exc
    return audio_path


def _initial_prompt(language: str) -> tuple[str | None, bool]:
    """Return the whisper initial prompt and whether it is the built-in default.

    The private vocabulary prompt wins (its prefix already primes punctuation).
    The Spanish default applies only to Spanish audio: for `auto` or any other
    language no default is passed, so it cannot bias the decoding language.
    """
    vocabulary = vocabulary_prompt(Path(os.environ.get(
        "SAURI_ASR_VOCABULARY_FILE", "~/.config/sauri/vocabulary.txt",
    )).expanduser())
    if vocabulary:
        return vocabulary, False
    if default_prompt_enabled() and language_code(language) == DEFAULT_PROMPT_LANGUAGE:
        return DEFAULT_PROMPT, True
    return None, False


def _run_whisper(
    wav_path: Path, output: Path, language: str, timeout_s: float, model_path: Path | None = None,
) -> dict[str, Any]:
    prompt, _ = _initial_prompt(language)
    command = [WHISPER_CLI, "-m", str(model_path or ASR_MODEL_PATH), "-f", str(wav_path),
         "-l", language_code(language), "-t", str(ASR_THREADS),
         "-bs", "5", "-bo", "5", "-fa"]
    if suppress_nst():
        command.append("-sns")
    if prompt:
        command.extend(["--prompt", prompt, "--carry-initial-prompt"])
    command.extend(["-ojf", "-of", str(output)])
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout_s)
    except subprocess.CalledProcessError as exc:
        logger.error("whisper-cli failed (exit_code=%s); stderr_tail=%s", exc.returncode, diagnostic_tail(exc.stderr))
        raise
    with output.with_suffix(".json").open() as result_file:
        result = json.load(result_file)
    if not isinstance(result, dict) or not isinstance(result.get("transcription"), list):
        raise ValueError("Invalid whisper output")
    return result


def _detected_language(doc: dict[str, Any]) -> str:
    language = doc.get("result", {}).get("language")
    if not isinstance(language, str) or language_code(language) == "auto":
        raise ValueError("Missing detected language")
    return language_code(language)


def _transcribe_wav(
    wav_path: Path, audio_ms: int, language: str, deadline: float, model_path: Path | None = None,
) -> tuple[WordsResult, str, dict[str, object], int]:
    # Without a chosen model the call is exactly the built-in one (no extra argument).
    model: dict[str, Any] = {} if model_path is None else {"model_path": model_path}
    if not vad_enabled():
        started = time.monotonic()
        doc = _run_whisper(wav_path, wav_path.parent / "out", language, remaining(deadline), **model)
        inference_ms = round((time.monotonic() - started) * 1000)
        remaining(deadline)
        return words_from_ggml_json(doc, audio_ms), _detected_language(doc), {
            "enabled": False, "speech_segments": None, "chunks": 1, "speech_ms": None,
            "skipped_ms": 0, "vad_ms": 0, "inference_ms": inference_ms,
        }, inference_ms
    started = time.monotonic()
    try:
        process = subprocess.run(
            [str(vad_cli_path()), "-f", str(wav_path), "-vm", str(vad_model_path()), "-vt", str(vad_threshold())],
            check=True, capture_output=True, text=True, timeout=remaining(deadline),
        )
    except subprocess.CalledProcessError as exc:
        logger.error("VAD failed (exit_code=%s); stderr_tail=%s", exc.returncode, diagnostic_tail(exc.stderr))
        raise
    vad_ms = round((time.monotonic() - started) * 1000)
    remaining(deadline)
    intervals = parse_vad(process.stdout, audio_ms)
    chunks = group_chunks(intervals, audio_ms, chunk_ms())
    if not chunks:
        logger.info("VAD found no speech (audio_ms=%d, vad_ms=%d)", audio_ms, vad_ms)
        raise NoSpeechError("no_speech")
    results = []
    detected: str | None = None
    inference_seconds = 0.0
    for interval in chunks:
        with tempfile.TemporaryDirectory(prefix="chunk-", dir=wav_path.parent) as temporary:
            chunk_path = Path(temporary) / "audio.wav"
            cut_wav(wav_path, chunk_path, interval, deadline)
            chunk_language = detected if language == "auto" and detected else language
            started = time.monotonic()
            doc = _run_whisper(chunk_path, Path(temporary) / "out", chunk_language, remaining(deadline), **model)
            inference_seconds += time.monotonic() - started
            remaining(deadline)
            result = words_from_ggml_json(doc, interval[1] - interval[0])
            if any(segment.words for segment in result.segments):
                if detected is None:
                    detected = _detected_language(doc)
                results.append((interval, result))
    if detected is None:
        raise NoWordTimestampsError("no_word_timestamps")
    inference_ms = round(inference_seconds * 1000)
    combined = align_chunks(results)
    remaining(deadline)
    return combined, detected, {
        "enabled": True, "speech_segments": len(intervals), "chunks": len(chunks),
        "speech_ms": sum(end - start for start, end in intervals),
        "skipped_ms": audio_ms - sum(end - start for start, end in chunks),
        "vad_ms": vad_ms, "inference_ms": inference_ms,
    }, inference_ms


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: TranscribeRequest,
    http_request: Request,
    _authorized: None = Depends(_require_engine_token),
    recording_capability: str | None = Header(default=None, alias="X-Sauri-Recording-Capability"),
    route: str | None = Header(default=None, alias=ROUTE_HEADER),
) -> TranscribeResponse | JSONResponse:
    _validate_audio_ref(request.audio_ref)
    _require_recording_capability(request.audio_ref, recording_capability)
    try:
        provider_route = asr_external.external_route(route)
    except RouteError as error:
        raise HTTPException(status_code=422, detail=error.reason or "route_malformed") from None
    if provider_route is not None:
        return await _transcribe_external(request, http_request, provider_route)
    try:
        selection = await run_in_threadpool(
            select_local_model, route, process="transcription", legacy_default=ASR_MODEL_PATH
        )
    except LocalModelError as error:
        raise HTTPException(status_code=error.status, detail=error.code) from None
    if s3_client is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    budget = server_budget()
    deadline = time.monotonic() + budget
    try:
        return await asyncio.wait_for(
            run_in_threadpool(_transcribe_serialized, request, deadline, selection), timeout=budget
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="engine_failed") from exc


def _provider_failure(error: ProviderError) -> JSONResponse:
    """The classified failure as ``{"error": {code, retryable, retry_after_s}}`` (no content, no key)."""
    return JSONResponse(status_code=asr_external.error_status(error), content=error.to_payload())


async def _transcribe_external(
    request: TranscribeRequest, http_request: Request, route: Route
) -> TranscribeResponse | JSONResponse:
    """Run an external route; the answer has the same v2 body as a local run (``device`` is ``remote``)."""
    if s3_client is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    deadline = time.monotonic() + server_budget()
    cancel = asyncio.Event()
    watcher = asyncio.create_task(asr_external.watch_disconnect(http_request.is_disconnected, cancel))
    try:
        return await _run_external(request, route, deadline, cancel)
    except AdapterCancelled:
        # The worker closed the connection: nobody reads this answer.
        return JSONResponse(status_code=499, content={"error": {"code": "cancelled"}})
    except ProviderError as error:
        logger.warning("External transcription failed (class=%s)", error.code)
        return _provider_failure(error)
    except NormalizeError as exc:
        raise HTTPException(status_code=422, detail="normalize_failed") from exc
    except KeepAwakeError as exc:
        raise HTTPException(status_code=503, detail="keep_awake_failed") from exc
    except TimeoutError:
        return _provider_failure(ProviderError("provider_timeout", reason="deadline"))
    except HTTPException:
        raise
    except Exception as exc:  # the type name only: messages may carry paths or provider text
        logger.error("External transcription failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="engine_failed") from exc
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def _vad_for_split() -> Any:
    return (
        vad_cli_runner(vad_cli_path(), vad_model_path(), vad_threshold(), timeout_s=300)
        if vad_enabled() else None
    )


async def _run_external(
    request: TranscribeRequest, route: Route, deadline: float, cancel: asyncio.Event
) -> TranscribeResponse:
    # Validation and the key come first: a refused route has not downloaded or sent anything.
    secret = await run_in_threadpool(asr_external.load_secret, route, secret_store)
    from sauri_engine_common.external.safe_http import SafeHttp  # httpx stays optional for local-only runs

    audio_path: str | None = None
    try:
        with KeepAwake(), tempfile.TemporaryDirectory(prefix="sauri-asr-") as temporary:
            started = time.monotonic()
            audio_path = await run_in_threadpool(_download_audio, request.audio_ref, deadline)
            download_ms = round((time.monotonic() - started) * 1000)
            if cancel.is_set():
                raise AdapterCancelled
            wav_path = Path(temporary) / "audio.wav"
            report = await run_in_threadpool(
                lambda: normalize_to_wav(Path(audio_path or ""), wav_path, timeout_s=min(300, remaining(deadline)))
            )
            outcome = await asr_external.transcribe_external(
                http=SafeHttp(max_response_bytes=asr_external.MAX_PROVIDER_RESPONSE_BYTES),
                route=route,
                secret=secret,
                wav=wav_path,
                language=request.language,
                cancel=cancel,
                deadline_s=remaining(deadline),
                allow_local=asr_external.allow_local_providers(),
                vad=_vad_for_split(),
            )
            if not outcome.result.words:
                raise HTTPException(status_code=422, detail="no_speech")
            return TranscribeResponse(
                segments=[Segment(text=s.text.strip(), start_ms=s.start_ms, end_ms=s.end_ms)
                          for s in outcome.segments],
                words=[Word(text=w.text, start_ms=w.start_ms, end_ms=w.end_ms, probability=w.probability,
                            timing_repaired=w.timing_repaired) for w in outcome.result.words],
                language=outcome.result.language,
                engine=EngineInfo(name=route.kind, model=route.model, device="remote"),
                diagnostics={
                    "audio_ms": report.audio_ms,
                    "inverted_words": 0,
                    "external": {
                        "parts": outcome.parts, "dropped_ms": outcome.dropped_ms,
                        "bitrate_bps": outcome.bitrate_bps,
                        "remote_deleted": outcome.result.diagnostics.get("remote_deleted"),
                    },
                    "stage_ms": {"download": download_ms, "normalize": round(report.seconds * 1000),
                                 "prepare": outcome.prepare_ms, "provider": outcome.provider_ms},
                },
            )
    finally:
        if audio_path is not None:
            with suppress(OSError):
                os.unlink(audio_path)


def _transcribe_serialized(
    request: TranscribeRequest, deadline: float, selection: LocalSelection | None = None,
) -> TranscribeResponse:
    if not _job_lock.acquire(timeout=remaining(deadline)):
        raise TimeoutError("engine_failed")
    try:
        remaining(deadline)
        return _transcribe_audio(request, deadline, selection)
    finally:
        _job_lock.release()


def _transcribe_audio(
    request: TranscribeRequest, deadline: float, selection: LocalSelection | None = None,
) -> TranscribeResponse:
    audio_path: str | None = None
    try:
        with KeepAwake(), tempfile.TemporaryDirectory(prefix="sauri-asr-") as temporary:
            started = time.monotonic()
            audio_path = _download_audio(request.audio_ref, deadline)
            download_ms = round((time.monotonic() - started) * 1000)
            wav_path = Path(temporary) / "audio.wav"
            report = normalize_to_wav(Path(audio_path), wav_path, timeout_s=min(300, remaining(deadline)))
            model: dict[str, Any] = {} if selection is None else {"model_path": selection.path}
            result, language, vad, inference_ms = _transcribe_wav(
                wav_path, report.audio_ms, request.language, deadline, **model)
            return TranscribeResponse(
                segments=[Segment(text=s.text.strip(), start_ms=s.start_ms, end_ms=s.end_ms) for s in result.segments],
                words=[Word(**asdict(word)) for segment in result.segments for word in segment.words],
                language=language,
                engine=EngineInfo(
                    name="whisper.cpp", model=MODEL_ID if selection is None else selection.model_id,
                    device=MODEL_DEVICE),
                diagnostics={
                    "audio_ms": report.audio_ms,
                    "vad": vad,
                    "inverted_words": result.inverted_words,
                    # Boolean only, never the prompt text. For `auto` it reflects the detected language.
                    "default_prompt": _initial_prompt(language)[1],
                    "stage_ms": {"download": download_ms, "normalize": round(report.seconds * 1000),
                                 "inference": inference_ms},
                },
            )
    except NormalizeError as exc:
        raise HTTPException(status_code=422, detail="normalize_failed") from exc
    except NoSpeechError as exc:
        raise HTTPException(status_code=422, detail="no_speech") from exc
    except NoWordTimestampsError as exc:
        raise HTTPException(status_code=500, detail="no_word_timestamps") from exc
    except KeepAwakeError as exc:
        raise HTTPException(status_code=503, detail="keep_awake_failed") from exc
    except Exception as exc:
        logger.error("Transcription failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="engine_failed") from exc
    finally:
        if audio_path is not None:
            with suppress(OSError):
                os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
