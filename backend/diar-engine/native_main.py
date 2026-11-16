"""Host-native Senko diarization service using CoreML."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal

import boto3
import diar_external
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sauri_engine_common import cancellation
from sauri_engine_common.audio import NormalizeError, normalize_to_wav
from sauri_engine_common.credentials import object_store_credentials
from sauri_engine_common.external.asr_common import AdapterCancelled
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.keep_awake import KeepAwake, KeepAwakeError
from sauri_engine_common.route import ROUTE_HEADER, Route, RouteError
from sauri_engine_common.secrets import SecretStore

logger = logging.getLogger("diar-engine-native")
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
MODEL_ID = "senko-coreml"
MODEL_DEVICE = "coreml"
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)

diarization_pipeline: Any = None
s3_client: Any = None
# Host secret store for provider keys; None means the default store (Keychain, else private files).
secret_store: SecretStore | None = None
_job_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Load Senko on CoreML and initialize MinIO without exposing credentials."""
    global diarization_pipeline, s3_client
    try:
        from senko import Diarizer  # type: ignore[import-not-found]

        with KeepAwake():
            pipeline = Diarizer(device="coreml", vad="pyannote", clustering="cpu", warmup=True, quiet=True)
            vad = pipeline.vad_processor_pyannote_coreml
            vad.lib.vad_set_min_duration_on(vad.processor, 0.0)
            vad.lib.vad_set_min_duration_off(vad.processor, 0.0)
        diarization_pipeline = pipeline
    except Exception as exc:
        raise RuntimeError("Unable to initialize native diarization pipeline") from exc
    access_key, secret_key = object_store_credentials()
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
    )
    logger.info("Native diarization initialized (model=%s, device=%s)", MODEL_ID, MODEL_DEVICE)
    yield
    diarization_pipeline = None
    s3_client = None


app = FastAPI(title="Sauri Native Diarization Engine", version="1.0.0", lifespan=lifespan)


class DiarizeRequest(BaseModel):
    audio_ref: str
    contract_version: Literal[2] = 2


class Segment(BaseModel):
    speaker: str
    start_ms: int
    end_ms: int


class EngineInfo(BaseModel):
    name: str
    model: str
    device: str


class DiarizeResponse(BaseModel):
    contract_version: Literal[2] = 2
    segments: list[Segment]
    speaker_count: int
    engine: EngineInfo
    diagnostics: dict[str, object] = {}


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


def _download_audio(audio_ref: str) -> str:
    if s3_client is None:
        raise RuntimeError("Object store is not initialized")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio_ref).suffix) as temp:
        audio_path = temp.name
    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, audio_path)
    except Exception as exc:
        with suppress(OSError):
            os.unlink(audio_path)
        raise RuntimeError("Audio download failed") from exc
    return audio_path


def _run_diarization(audio_path: str) -> tuple[list[Segment], int]:
    if diarization_pipeline is None:
        raise RuntimeError("Diarization pipeline not loaded")
    result = diarization_pipeline.diarize(wav_path=str(audio_path), accurate=True, generate_colors=False)
    # Senko returns None (not a result dictionary) when VAD finds no voice.
    if result is None:
        return [], 0
    segments = []
    dropped_segments = 0
    for segment in result["raw_segments"]:
        start_ms = round(segment["start"] * 1000)
        end_ms = round(segment["end"] * 1000)
        if end_ms <= start_ms:
            dropped_segments += 1
            continue
        segments.append(Segment(speaker=str(segment["speaker"]), start_ms=start_ms, end_ms=end_ms))
    segments.sort(key=lambda segment: (segment.start_ms, segment.end_ms))
    return segments, dropped_segments


@app.post("/diarize", response_model=DiarizeResponse)
async def diarize(
    request: DiarizeRequest,
    http_request: Request,
    _authorized: None = Depends(_require_engine_token),
    recording_capability: str | None = Header(default=None, alias="X-Sauri-Recording-Capability"),
    route: str | None = Header(default=None, alias=ROUTE_HEADER),
) -> DiarizeResponse | JSONResponse:
    _validate_audio_ref(request.audio_ref)
    _require_recording_capability(request.audio_ref, recording_capability)
    try:
        provider_route = diar_external.external_route(route)
    except RouteError as error:
        raise HTTPException(status_code=422, detail=error.reason or "route_malformed") from None
    if provider_route is not None:
        return await _diarize_external(request, http_request, provider_route)
    if diarization_pipeline is None:
        raise HTTPException(status_code=503, detail="Diarization pipeline not loaded")
    # Stops at the next checkpoint once the worker disconnects (the Senko call itself cannot be interrupted).
    left = threading.Event()
    token = cancellation.bind(left)
    watcher = asyncio.create_task(cancellation.cancel_on_disconnect(http_request.is_disconnected, left))
    try:
        return await run_in_threadpool(_diarize_serialized, request.audio_ref)
    except cancellation.JobCancelled as exc:
        logger.info("Diarization stopped: the caller left")
        raise HTTPException(status_code=499, detail="client_closed") from exc
    finally:
        left.set()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        cancellation.unbind(token)


def _provider_failure(error: ProviderError) -> JSONResponse:
    """The classified failure as ``{"error": {code, retryable, retry_after_s}}`` (no content, no key)."""
    return JSONResponse(status_code=diar_external.error_status(error), content=error.to_payload())


async def _diarize_external(
    request: DiarizeRequest, http_request: Request, route: Route
) -> DiarizeResponse | JSONResponse:
    """Run an external route; the answer has the same v2 body as a local run (``device`` is ``remote``)."""
    if s3_client is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    cancel = asyncio.Event()
    watcher = asyncio.create_task(diar_external.watch_disconnect(http_request.is_disconnected, cancel))
    try:
        return await _run_external(request, route, cancel)
    except AdapterCancelled:
        # The worker closed the connection: nobody reads this answer.
        return JSONResponse(status_code=499, content={"error": {"code": "cancelled"}})
    except ProviderError as error:
        logger.warning("External diarization failed (class=%s)", error.code)
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
        logger.error("External diarization failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="engine_failed") from exc
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def _run_external(request: DiarizeRequest, route: Route, cancel: asyncio.Event) -> DiarizeResponse:
    # Validation and the key come first: a refused route has not downloaded or sent anything.
    secret = await run_in_threadpool(diar_external.load_secret, route, secret_store)
    from sauri_engine_common.external.safe_http import SafeHttp  # httpx stays optional for local-only runs

    budget = min(diar_external.EXTERNAL_BUDGET_S, route.timeouts.total_s)
    deadline = time.monotonic() + budget

    def left() -> float:
        return max(deadline - time.monotonic(), 1.0)

    audio_path: str | None = None
    try:
        with KeepAwake(), tempfile.TemporaryDirectory(prefix="sauri-diar-") as temporary:
            started = time.monotonic()
            audio_path = await run_in_threadpool(_download_audio, request.audio_ref)
            download_ms = round((time.monotonic() - started) * 1000)
            if cancel.is_set():
                raise AdapterCancelled
            wav_path = Path(temporary) / "audio.wav"
            report = await run_in_threadpool(
                lambda: normalize_to_wav(Path(audio_path or ""), wav_path, timeout_s=min(300, left()))
            )
            outcome = await diar_external.diarize_external(
                http=SafeHttp(max_response_bytes=diar_external.MAX_PROVIDER_RESPONSE_BYTES),
                route=route,
                secret=secret,
                wav=wav_path,
                cancel=cancel,
                deadline_s=left(),
                allow_local=diar_external.allow_local_providers(),
            )
            # The local contract has no zero-length segment: drop and count them, as Senko's wrapper does.
            kept = [s for s in outcome.result.segments if s.end_ms > s.start_ms]
            segments = [Segment(speaker=s.raw_label, start_ms=s.start_ms, end_ms=s.end_ms) for s in kept]
            diagnostics = outcome.result.diagnostics
            return DiarizeResponse(
                segments=segments,
                speaker_count=len({s.speaker for s in segments}),
                engine=EngineInfo(name=route.kind, model=route.model, device="remote"),
                diagnostics={
                    "audio_ms": report.audio_ms,
                    "dropped_segments": len(outcome.result.segments) - len(kept),
                    "external": {
                        "parts": outcome.parts, "dropped_ms": outcome.dropped_ms,
                        "bitrate_bps": outcome.bitrate_bps,
                        "remote_deleted": diagnostics.get("remote_deleted"),
                        "label_policy": diagnostics.get("label_policy"),
                        "speaker_count_per_part": diagnostics.get("speaker_count_per_part"),
                        "timing_repaired": diagnostics.get("timing_repaired"),
                    },
                    "stage_ms": {"download": download_ms, "normalize": round(report.seconds * 1000),
                                 "prepare": outcome.prepare_ms, "provider": outcome.provider_ms},
                },
            )
    finally:
        if audio_path is not None:
            with suppress(OSError):
                os.unlink(audio_path)


def _diarize_serialized(audio_ref: str) -> DiarizeResponse:
    # Senko mutates per-run state; keep jobs serial while freeing the event loop.
    cancellation.acquire(_job_lock, float("inf"))
    try:
        return _diarize_audio(audio_ref)
    finally:
        _job_lock.release()


def _diarize_audio(audio_ref: str) -> DiarizeResponse:
    audio_path: str | None = None
    wav_path: Path | None = None
    try:
        with KeepAwake():
            started = time.monotonic()
            cancellation.checkpoint()
            try:
                audio_path = _download_audio(audio_ref)
            except Exception as exc:
                raise HTTPException(status_code=500, detail="Audio download failed") from exc
            download_ms = round((time.monotonic() - started) * 1000)
            wav_path = Path(audio_path + ".wav")
            try:
                report = normalize_to_wav(Path(audio_path), wav_path)
            except NormalizeError as exc:
                raise HTTPException(status_code=422, detail=exc.code) from exc
            cancellation.checkpoint()  # nothing started yet that cannot be stopped
            started = time.monotonic()
            try:
                segments, dropped_segments = _run_diarization(str(wav_path))
            except Exception as exc:
                logger.error("Diarization failed (%s)", type(exc).__name__)
                raise HTTPException(status_code=500, detail="Diarization failed") from exc
            return DiarizeResponse(
                segments=segments,
                speaker_count=len({segment.speaker for segment in segments}),
                engine=EngineInfo(name="senko", model=MODEL_ID, device=MODEL_DEVICE),
                diagnostics={
                    "audio_ms": report.audio_ms,
                    "dropped_segments": dropped_segments,
                    "stage_ms": {"download": download_ms, "normalize": round(report.seconds * 1000),
                                 "inference": round((time.monotonic() - started) * 1000)},
                },
            )
    except KeepAwakeError as exc:
        raise HTTPException(status_code=503, detail="keep_awake_failed") from exc
    finally:
        for path in (audio_path, wav_path):
            if path is not None:
                with suppress(OSError):
                    os.unlink(path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
