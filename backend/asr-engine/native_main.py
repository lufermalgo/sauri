"""Host-native ASR service using mlx-whisper on Apple silicon."""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("asr-engine-native")
logging.basicConfig(level=logging.INFO)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
MODEL_ID = os.environ.get("ASR_MODEL", "mlx-community/whisper-large-v3-turbo")
MODEL_DEVICE = "mlx"

transcribe_audio: Any = None
s3_client: Any = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load the MLX inference function and initialize MinIO at process start."""
    global transcribe_audio, s3_client
    try:
        import mlx_whisper

        transcribe_audio = mlx_whisper.transcribe
    except Exception as exc:
        raise RuntimeError("Unable to initialize mlx-whisper") from exc
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    logger.info("Native ASR initialized (model=%s)", MODEL_ID)
    yield
    transcribe_audio = None
    s3_client = None


app = FastAPI(title="Sauri Native ASR Engine", version="1.0.0", lifespan=lifespan)


class TranscribeRequest(BaseModel):
    audio_ref: str
    language: str = "es-CO"


class Segment(BaseModel):
    text: str
    start_ms: int
    end_ms: int


class TranscribeResponse(BaseModel):
    segments: list[Segment]
    language: str


def _download_audio(audio_ref: str) -> str:
    if s3_client is None:
        raise RuntimeError("Object store is not initialized")
    suffix = Path(audio_ref).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        audio_path = temp.name
    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, audio_path)
    except Exception as exc:
        with suppress(OSError):
            os.unlink(audio_path)
        raise RuntimeError("Audio download failed") from exc
    return audio_path


def _language_code(language: str) -> str | None:
    base = language.split("-", maxsplit=1)[0].strip().lower()
    return base or None


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    if transcribe_audio is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        audio_path = _download_audio(request.audio_ref)
    except Exception as exc:
        logger.error("Audio download failed")
        raise HTTPException(status_code=500, detail="Audio download failed") from exc

    try:
        result = transcribe_audio(
            audio_path,
            path_or_hf_repo=MODEL_ID,
            language=_language_code(request.language),
            verbose=False,
        )
        segments = [
            Segment(
                text=str(segment.get("text", "")).strip(),
                start_ms=int(float(segment["start"]) * 1000),
                end_ms=int(float(segment["end"]) * 1000),
            )
            for segment in result.get("segments", [])
            if str(segment.get("text", "")).strip()
        ]
        language = str(result.get("language") or request.language)
        return TranscribeResponse(segments=segments, language=language)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed")
        raise HTTPException(status_code=500, detail="Transcription failed") from exc
    finally:
        with suppress(OSError):
            os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
