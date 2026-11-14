"""Host-native pyannote diarization service using Apple MPS."""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import wave
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger("diar-engine-native")
logging.basicConfig(level=logging.INFO)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
MINIO_AUDIO_PREFIX = os.environ.get("MINIO_AUDIO_PREFIX", "recordings/")
FFMPEG_TIMEOUT_SECONDS = 60
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
MODEL_ID = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
MODEL_DEVICE = os.environ.get("DIARIZATION_DEVICE", "mps")
HF_TOKEN_PATH = Path(os.environ.get("HF_TOKEN_PATH", Path.home() / ".config" / "sauri" / "hf_token"))
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)

diarization_pipeline: Any = None
s3_client: Any = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load pyannote on MPS and initialize MinIO without exposing credentials."""
    global diarization_pipeline, s3_client
    try:
        import torch
        from pyannote.audio import Pipeline
        from pyannote.audio.core.task import Problem, Resolution, Specifications
        from torch.torch_version import TorchVersion

        token = HF_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("Hugging Face token file is empty")
        # Torch >=2.6 defaults to weights-only loading. These existing pyannote
        # checkpoints contain only four additional schema/version types. Scope
        # that explicit allowlist to loading; never disable weights-only safety.
        with torch.serialization.safe_globals([Specifications, Problem, Resolution, TorchVersion]):
            pipeline = Pipeline.from_pretrained(MODEL_ID, use_auth_token=token)
        pipeline.to(torch.device(MODEL_DEVICE))
        diarization_pipeline = pipeline
    except Exception as exc:
        raise RuntimeError("Unable to initialize native diarization pipeline") from exc
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    logger.info("Native diarization initialized (model=%s, device=%s)", MODEL_ID, MODEL_DEVICE)
    yield
    diarization_pipeline = None
    s3_client = None


app = FastAPI(title="Sauri Native Diarization Engine", version="1.0.0", lifespan=lifespan)


class DiarizeRequest(BaseModel):
    audio_ref: str


class Segment(BaseModel):
    speaker: str
    start_ms: int
    end_ms: int


class DiarizeResponse(BaseModel):
    segments: list[Segment]
    num_speakers: int


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


def _convert_to_wav(audio_path: str) -> io.BytesIO:
    """Decode the complete original to seekable PCM16 WAV in RAM, never a disk derivative."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed; cannot decode audio to WAV")

    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                audio_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Audio conversion failed ({type(exc).__name__})") from exc
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(result.stdout)
    audio.seek(0)
    return audio


def _run_diarization(audio: io.BytesIO) -> list[Segment]:
    if diarization_pipeline is None:
        raise RuntimeError("Diarization pipeline not loaded")
    annotation = diarization_pipeline(audio)
    segments: list[Segment] = []
    for turn, _track, speaker in annotation.itertracks(yield_label=True):
        start_ms = int(turn.start * 1000)
        end_ms = int(turn.end * 1000)
        if end_ms > start_ms:
            segments.append(Segment(speaker=str(speaker), start_ms=start_ms, end_ms=end_ms))
    segments.sort(key=lambda segment: (segment.start_ms, segment.end_ms))
    return segments


@app.post("/diarize", response_model=DiarizeResponse)
async def diarize(
    request: DiarizeRequest,
    _authorized: None = Depends(_require_engine_token),
    recording_capability: str | None = Header(default=None, alias="X-Sauri-Recording-Capability"),
) -> DiarizeResponse:
    _validate_audio_ref(request.audio_ref)
    _require_recording_capability(request.audio_ref, recording_capability)
    if diarization_pipeline is None:
        raise HTTPException(status_code=503, detail="Diarization pipeline not loaded")
    try:
        audio_path = _download_audio(request.audio_ref)
    except Exception as exc:
        logger.error("Audio download failed")
        raise HTTPException(status_code=500, detail="Audio download failed") from exc
    try:
        wav_audio = _convert_to_wav(audio_path)
    except Exception as exc:
        logger.error("Audio conversion failed (%s)", type(exc).__name__)
        with suppress(OSError):
            os.unlink(audio_path)
        raise HTTPException(status_code=500, detail="Audio conversion failed") from exc
    try:
        segments = _run_diarization(wav_audio)
        return DiarizeResponse(
            segments=segments,
            num_speakers=len({segment.speaker for segment in segments}),
        )
    except Exception as exc:
        logger.error("Diarization failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Diarization failed") from exc
    finally:
        with suppress(OSError):
            os.unlink(audio_path)
        wav_audio.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
