"""Host-native pyannote diarization service using Apple MPS."""

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

logger = logging.getLogger("diar-engine-native")
logging.basicConfig(level=logging.INFO)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
MODEL_ID = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
MODEL_DEVICE = os.environ.get("DIARIZATION_DEVICE", "mps")
HF_TOKEN_PATH = Path(os.environ.get("HF_TOKEN_PATH", Path.home() / ".config" / "sauri" / "hf_token"))

diarization_pipeline: Any = None
s3_client: Any = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load pyannote on MPS and initialize MinIO without exposing credentials."""
    global diarization_pipeline, s3_client
    try:
        import torch
        from pyannote.audio import Pipeline

        token = HF_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("Hugging Face token file is empty")
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


def _run_diarization(audio_path: str) -> list[Segment]:
    if diarization_pipeline is None:
        raise RuntimeError("Diarization pipeline not loaded")
    annotation = diarization_pipeline(audio_path)
    segments: list[Segment] = []
    for turn, _track, speaker in annotation.itertracks(yield_label=True):
        start_ms = int(turn.start * 1000)
        end_ms = int(turn.end * 1000)
        if end_ms > start_ms:
            segments.append(Segment(speaker=str(speaker), start_ms=start_ms, end_ms=end_ms))
    segments.sort(key=lambda segment: (segment.start_ms, segment.end_ms))
    return segments


@app.post("/diarize", response_model=DiarizeResponse)
async def diarize(request: DiarizeRequest) -> DiarizeResponse:
    if diarization_pipeline is None:
        raise HTTPException(status_code=503, detail="Diarization pipeline not loaded")
    try:
        audio_path = _download_audio(request.audio_ref)
    except Exception as exc:
        logger.error("Audio download failed")
        raise HTTPException(status_code=500, detail="Audio download failed") from exc
    try:
        segments = _run_diarization(audio_path)
        return DiarizeResponse(
            segments=segments,
            num_speakers=len({segment.speaker for segment in segments}),
        )
    except Exception as exc:
        logger.error("Diarization failed")
        raise HTTPException(status_code=500, detail="Diarization failed") from exc
    finally:
        with suppress(OSError):
            os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
