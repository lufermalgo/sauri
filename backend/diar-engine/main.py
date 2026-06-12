"""Diar Engine — FastAPI service backed by pyannote.audio.

Downloads audio from the object store (MinIO/S3) using the provided
audio_ref, runs real speaker diarization with pyannote.audio, and returns
speaker segments with millisecond timestamps.

Mirrors the structure of the sibling asr-engine service.

Contract:
  POST /diarize
  Input:  { "audio_ref": str }
  Output: { "segments": [{"speaker": str, "start_ms": int, "end_ms": int}, ...],
            "num_speakers": int }

  GET /health -> { "status": "ok" }
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager

import boto3
import torch
from botocore.config import Config
from fastapi import FastAPI, HTTPException
from pyannote.audio import Pipeline
from pydantic import BaseModel

logger = logging.getLogger("diar-engine")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Configuration (env vars)
# ---------------------------------------------------------------------------

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")

# pyannote speaker-diarization pipeline. The 3.1 community pipeline is the
# standard, current default. Gated models require a Hugging Face access token.
DIARIZATION_MODEL = os.environ.get(
    "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
DIARIZATION_DEVICE = os.environ.get("DIARIZATION_DEVICE", "cpu")

# ---------------------------------------------------------------------------
# Global resources initialized at startup
# ---------------------------------------------------------------------------

diarization_pipeline: Pipeline | None = None
s3_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the diarization pipeline and S3 client at startup."""
    global diarization_pipeline, s3_client

    logger.info("Loading pyannote diarization pipeline model=%s", DIARIZATION_MODEL)
    diarization_pipeline = Pipeline.from_pretrained(
        DIARIZATION_MODEL,
        use_auth_token=HF_TOKEN,
    )
    # Move the pipeline to the configured device (cpu/cuda).
    diarization_pipeline.to(torch.device(DIARIZATION_DEVICE))
    logger.info("Diarization pipeline loaded successfully on %s", DIARIZATION_DEVICE)

    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    logger.info(
        "S3 client initialized (endpoint=%s, bucket=%s)", MINIO_ENDPOINT, MINIO_BUCKET
    )

    yield

    # Cleanup (nothing to explicitly close for these resources)
    diarization_pipeline = None
    s3_client = None


app = FastAPI(
    title="sauri Diar Engine",
    description="Local speaker diarization service powered by pyannote.audio",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DiarizeRequest(BaseModel):
    """Request body for the /diarize endpoint."""

    audio_ref: str


class Segment(BaseModel):
    """A speaker segment with millisecond timestamps."""

    speaker: str
    start_ms: int
    end_ms: int


class DiarizeResponse(BaseModel):
    """Response from the /diarize endpoint."""

    segments: list[Segment]
    num_speakers: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download_audio_from_s3(audio_ref: str) -> str:
    """Download audio from S3/MinIO to a temporary file. Returns the temp file path."""
    assert s3_client is not None, "S3 client not initialized"

    # Determine file extension from the key for decoder compatibility
    ext = ""
    if "." in audio_ref:
        ext = "." + audio_ref.rsplit(".", 1)[-1]

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, tmp.name)
    except Exception as e:
        # Clean up temp file on download failure
        os.unlink(tmp.name)
        raise RuntimeError(
            f"Failed to download audio_ref={audio_ref!r} from bucket={MINIO_BUCKET!r}: {e}"
        ) from e

    return tmp.name


def _run_diarization(audio_path: str) -> list[Segment]:
    """Run the pyannote diarization pipeline on a local audio file.

    Returns the speaker segments ordered ascending by start_ms.
    """
    assert diarization_pipeline is not None, "Diarization pipeline not loaded"

    annotation = diarization_pipeline(audio_path)

    segments: list[Segment] = []
    # pyannote yields (segment, track, speaker_label) tuples.
    for turn, _track, speaker in annotation.itertracks(yield_label=True):
        start_ms = int(turn.start * 1000)
        end_ms = int(turn.end * 1000)
        # Skip degenerate (non-positive duration) turns.
        if end_ms <= start_ms:
            continue
        segments.append(Segment(speaker=str(speaker), start_ms=start_ms, end_ms=end_ms))

    # Contract: segments ordered ascending by start_ms (stable on end_ms).
    segments.sort(key=lambda s: (s.start_ms, s.end_ms))
    return segments


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/diarize", response_model=DiarizeResponse)
async def diarize(request: DiarizeRequest) -> DiarizeResponse:
    """Diarize the audio referenced by audio_ref.

    Downloads the audio from MinIO, runs pyannote.audio speaker diarization,
    and returns the speaker segments (ordered by start_ms) plus the number of
    distinct speakers detected.
    """
    if diarization_pipeline is None:
        raise HTTPException(status_code=503, detail="Diarization pipeline not loaded")

    # 1. Download audio from object store
    try:
        audio_path = _download_audio_from_s3(request.audio_ref)
    except Exception as e:
        logger.error("Failed to download audio: %s", e)
        raise HTTPException(status_code=500, detail=f"Audio download failed: {e}")

    try:
        # 2. Run real diarization and collect ordered segments
        segments = _run_diarization(audio_path)

        # 3. Count distinct speakers
        num_speakers = len({segment.speaker for segment in segments})

        return DiarizeResponse(segments=segments, num_speakers=num_speakers)

    except Exception as e:
        logger.error("Diarization failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Diarization failed: {e}")

    finally:
        # 4. Clean up temporary file
        try:
            os.unlink(audio_path)
        except OSError:
            pass


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
