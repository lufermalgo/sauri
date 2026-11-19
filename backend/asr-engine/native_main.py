"""Host-native ASR service: Parakeet (Core ML, the default when installed) or whisper.cpp on Metal.

One model serves each request. ``local:default`` resolves, before the request runs, to the catalog's preferred
model (Parakeet ultra) when it is installed and its engine is healthy, and to the built-in Whisper model otherwise;
``local:<id>`` is that model or a refusal. A Parakeet failure, an unusable output (empty, broken timestamps) and a
language Parakeet cannot serve fail the request with a stable code (``model_failed``, ``language_not_supported``);
a text its quality guards flag (drift, repetition) is returned with a logged warning. No other model transcribes
the audio again: the user can retry, or choose Whisper and regenerate.

Whisper's files (its model and the voice detector it runs with) are needed only by requests that use Whisper:
the engine starts without them, and such a request is refused with ``model_not_installed`` (or
``model_not_verified`` when a file present at startup is not the pinned one).
"""

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
import asr_parakeet
import boto3
from asr_assets import file_problem, vad_cli_path, vad_model_path, verify_runtime
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
from asr_diagnostics import diagnostic_tail, whisper_load_failed
from asr_prompt import DEFAULT_PROMPT, DEFAULT_PROMPT_LANGUAGE, vocabulary_prompt
from asr_vad import align_chunks, cut_wav, group_chunks, parse_vad
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sauri_engine_common import cancellation
from sauri_engine_common.audio import NormalizeError, normalize_to_wav
from sauri_engine_common.credentials import object_store_credentials
from sauri_engine_common.custom_models import is_custom_id
from sauri_engine_common.external.asr_common import AdapterCancelled
from sauri_engine_common.external.audio_prep import vad_cli_runner
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.keep_awake import KeepAwake, KeepAwakeError
from sauri_engine_common.local_media import InvalidMediaPathError, local_media_path
from sauri_engine_common.local_model_use import (
    LocalModelError,
    LocalSelection,
    load_runtime_catalog,
    select_local_model,
    select_preferred,
)
from sauri_engine_common.process_group import kill_all as kill_helpers
from sauri_engine_common.process_group import run as run_group
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
# Built-in whisper.cpp files (model, voice detector) present at startup that are not the pinned ones.
_unverified_files: set[Path] = set()
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
    asr_parakeet.guard_config()
    asr_parakeet.default_engine()
    if vad_enabled():
        vad_threshold()
        chunk_ms()
    try:
        manifest = verify_runtime(Path(WHISPER_CLI))
        _check_whisper_files(manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Native ASR asset verification failed") from exc
    if not os.environ.get("SAURI_RECORDINGS_DIR"):
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
    logger.info("Native ASR initialized (model=%s, parakeet_ready=%s)", MODEL_ID, _parakeet_default() is not None)
    threading.Thread(target=_warm_parakeet, name="parakeet-warm", daemon=True).start()
    yield
    kill_helpers()  # no whisper-cli or VAD process may outlive the engine
    s3_client = None


def _whisper_files() -> list[tuple[str, Path]]:
    """The built-in whisper.cpp files a Whisper request needs, by manifest section."""
    files = [("asr", ASR_MODEL_PATH)]
    if vad_enabled():
        files.append(("vad", vad_model_path()))
    return files


def _check_whisper_files(manifest: dict[str, Any]) -> None:
    """Hash the built-in Whisper files that are present; a mismatch refuses Whisper requests, not the engine."""
    _unverified_files.clear()
    for section, path in _whisper_files():
        problem = file_problem(path, manifest if section == "asr" else manifest["vad"])
        if problem == "model_not_verified":
            _unverified_files.add(path)
        logger.info("Whisper file %s: %s", section, problem or "verified")


def _file_problem(path: Path) -> str | None:
    """Why a Whisper request cannot use ``path`` now (``None`` when it can); cheap: startup did the hashing."""
    if path in _unverified_files:
        return "model_not_verified"
    return None if path.is_file() else "model_not_installed"


def _parakeet_default() -> LocalSelection | None:
    """The Parakeet model when ``local:default`` would use it now (installed, verified, binary healthy)."""
    if asr_parakeet.default_engine() != "auto":
        return None
    return select_preferred(
        process="transcription",
        ready=lambda entry: entry.engine == asr_parakeet.CATALOG_ENGINE and asr_parakeet.engine_ready(),
    )


def _warm_parakeet() -> None:
    """Compile the Core ML models once in the background so the first recording is not slow; never raises."""
    try:
        selection = _parakeet_default()
        if selection is None:
            return
        entry = load_runtime_catalog().get(selection.model_id)
        if entry is None or entry.sha256 is None or asr_parakeet.is_warm(entry.sha256):
            return
        if _job_lock.acquire(blocking=False):  # a recording in progress compiles it anyway
            try:
                asr_parakeet.warm(selection.path, entry.sha256)
            finally:
                _job_lock.release()
    except Exception as exc:  # warm-up is an optimization
        logger.warning("Parakeet warm-up skipped (%s)", type(exc).__name__)


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
    if root := os.environ.get("SAURI_RECORDINGS_DIR"):
        try:
            local_media_path(Path(root), audio_ref)
        except InvalidMediaPathError as exc:
            raise HTTPException(status_code=400, detail="invalid_media_path") from exc
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
    if root := os.environ.get("SAURI_RECORDINGS_DIR"):
        remaining(deadline)
        return str(local_media_path(Path(root), audio_ref))
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


class WhisperModelLoadError(Exception):
    """whisper-cli could not load a chosen model; it stopped before processing any audio."""


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
        run_group(command, check=True, capture_output=True, timeout=timeout_s)
    except subprocess.CalledProcessError as exc:
        logger.error("whisper-cli failed (exit_code=%s); stderr_tail=%s", exc.returncode, diagnostic_tail(exc.stderr))
        if model_path is not None and whisper_load_failed(exc.returncode, exc.stderr):
            raise WhisperModelLoadError from exc
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
    cancellation.checkpoint()
    started = time.monotonic()
    try:
        process = run_group(
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
        cancellation.checkpoint()  # the worker left: do not start the remaining chunks
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
    if s3_client is None and not os.environ.get("SAURI_RECORDINGS_DIR"):
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        selection = await run_in_threadpool(_select_engine, route, request.language)
    except LocalModelError as error:
        raise HTTPException(status_code=error.status, detail=error.code) from None
    budget = server_budget()
    deadline = time.monotonic() + budget
    # The thread stops at its next checkpoint once the worker disconnects or this request ends.
    left = threading.Event()
    token = cancellation.bind(left)
    watcher = asyncio.create_task(cancellation.cancel_on_disconnect(http_request.is_disconnected, left))
    try:
        return await asyncio.wait_for(
            run_in_threadpool(_transcribe_serialized, request, deadline, selection), timeout=budget
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="engine_failed") from exc
    except cancellation.JobCancelled as exc:  # left while waiting for the job slot
        raise HTTPException(status_code=499, detail="client_closed") from exc
    finally:
        left.set()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        cancellation.unbind(token)


def _select_engine(header: str | None, language: str) -> LocalSelection | None:
    """The one local model of this request; ``None`` means the built-in whisper.cpp model.

    An explicit ``local:<id>`` is honored or refused, never replaced. ``local:default`` (or no route) is Parakeet
    when it is installed and healthy, else Whisper. The chosen model's own files must be there: a request is
    refused before any audio is read when they are not, or when Parakeet cannot serve its language.
    """
    selection = select_local_model(header, process="transcription", legacy_default=ASR_MODEL_PATH)
    if selection is None:
        selection = _parakeet_default()
    if selection is not None and selection.engine == asr_parakeet.CATALOG_ENGINE:
        if not asr_parakeet.serves_language(language):
            raise LocalModelError(422, "language_not_supported")
        return selection
    for section, path in _whisper_files():
        if selection is not None and section == "asr":
            continue  # a chosen Whisper model was located (and vouched for) by select_local_model
        if (problem := _file_problem(path)) is not None:
            raise LocalModelError(409, problem)
    return selection


def _provider_failure(error: ProviderError) -> JSONResponse:
    """The classified failure as ``{"error": {code, retryable, retry_after_s}}`` (no content, no key)."""
    return JSONResponse(status_code=asr_external.error_status(error), content=error.to_payload())


async def _transcribe_external(
    request: TranscribeRequest, http_request: Request, route: Route
) -> TranscribeResponse | JSONResponse:
    """Run an external route; the answer has the same v2 body as a local run (``device`` is ``remote``)."""
    if s3_client is None and not os.environ.get("SAURI_RECORDINGS_DIR"):
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
    """Pauses to split an upload at; without the voice detector (a Parakeet-only Mac) parts are cut by size."""
    if not vad_enabled() or _file_problem(vad_model_path()) is not None:
        return None
    return vad_cli_runner(vad_cli_path(), vad_model_path(), vad_threshold(), timeout_s=300)


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
        if audio_path is not None and not os.environ.get("SAURI_RECORDINGS_DIR"):
            with suppress(OSError):
                os.unlink(audio_path)


def _transcribe_serialized(
    request: TranscribeRequest, deadline: float, selection: LocalSelection | None = None,
) -> TranscribeResponse:
    if not cancellation.acquire(_job_lock, remaining(deadline)):
        raise TimeoutError("engine_failed")
    try:
        remaining(deadline)
        return _transcribe_audio(request, deadline, selection)
    finally:
        _job_lock.release()


def _parakeet_response(
    wav_path: Path, audio_ms: int, language: str, selection: LocalSelection, deadline: float,
    stage_ms: dict[str, int],
) -> TranscribeResponse:
    """Transcribe with Parakeet or raise ``ParakeetRejected``; the contract-v2 answer carries the engine's own words."""
    result = asr_parakeet.transcribe(wav_path, audio_ms, language, selection.path, remaining(deadline))
    return TranscribeResponse(
        segments=[Segment(text=s.text.strip(), start_ms=s.start_ms, end_ms=s.end_ms) for s in result.segments],
        words=[Word(**asdict(word)) for segment in result.segments for word in segment.words],
        language=language,
        engine=EngineInfo(name=asr_parakeet.ENGINE_NAME, model=selection.model_id, device=asr_parakeet.DEVICE),
        diagnostics={
            "audio_ms": audio_ms,
            "vad": {"enabled": False, "speech_segments": None, "chunks": 1, "speech_ms": None,
                    "skipped_ms": 0, "vad_ms": 0, "inference_ms": result.cli_ms},
            "inverted_words": result.words.inverted_words,
            "default_prompt": False,
            "parakeet": {
                "confidence": result.confidence, "rtfx": result.rtfx,
                "english_stopword_rate": round(result.english_rate, 4),
                "guard_warning": result.guard_warning,
            },
            "stage_ms": {**stage_ms, "inference": result.cli_ms},
        },
    )


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
            cancellation.checkpoint()
            stage_ms = {"download": download_ms, "normalize": round(report.seconds * 1000)}
            if selection is not None and selection.engine == asr_parakeet.CATALOG_ENGINE:
                return _parakeet_response(wav_path, report.audio_ms, request.language, selection, deadline, stage_ms)
            model: dict[str, Any] = {} if selection is None else {"model_path": selection.path}
            try:
                result, language, vad, inference_ms = _transcribe_wav(
                    wav_path, report.audio_ms, request.language, deadline, **model)
            except WhisperModelLoadError:
                if selection is None or not is_custom_id(selection.model_id):
                    raise  # a catalog model that does not load stays a failure (engine_failed)
                # A custom model whisper.cpp cannot load: once, the model local:default would run.
                logger.warning("custom_model_load_failed model=%s fallback=default", selection.model_id)
                selection = _select_engine(None, request.language)
                if selection is not None and selection.engine == asr_parakeet.CATALOG_ENGINE:
                    return _parakeet_response(
                        wav_path, report.audio_ms, request.language, selection, deadline, stage_ms)
                result, language, vad, inference_ms = _transcribe_wav(
                    wav_path, report.audio_ms, request.language, deadline)
            diagnostics: dict[str, object] = {
                "audio_ms": report.audio_ms,
                "vad": vad,
                "inverted_words": result.inverted_words,
                # Boolean only, never the prompt text. For `auto` it reflects the detected language.
                "default_prompt": _initial_prompt(language)[1],
                "stage_ms": {**stage_ms, "inference": inference_ms},
            }
            return TranscribeResponse(
                segments=[Segment(text=s.text.strip(), start_ms=s.start_ms, end_ms=s.end_ms) for s in result.segments],
                words=[Word(**asdict(word)) for segment in result.segments for word in segment.words],
                language=language,
                engine=EngineInfo(
                    name="whisper.cpp", model=MODEL_ID if selection is None else selection.model_id,
                    device=MODEL_DEVICE),
                diagnostics=diagnostics,
            )
    except cancellation.JobCancelled as exc:
        logger.info("Transcription stopped: the caller left")
        raise HTTPException(status_code=499, detail="client_closed") from exc
    except asr_parakeet.ParakeetRejected as rejected:
        # Parakeet is this request's one model: the transcription fails; the reason code goes to the log only.
        status, code = asr_parakeet.failure(rejected.reason)
        logger.warning("Parakeet transcription failed (reason=%s)", rejected.reason)
        raise HTTPException(status_code=status, detail=code) from None
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
        if audio_path is not None and not os.environ.get("SAURI_RECORDINGS_DIR"):
            with suppress(OSError):
                os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
