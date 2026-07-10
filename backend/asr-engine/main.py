"""ASR Engine — FastAPI service backed by faster-whisper.

Downloads audio from the object store (MinIO/S3) using the provided
audio_ref, transcribes it with faster-whisper, and returns segments
with millisecond timestamps.

Contract:
  POST /transcribe
  Input:  { "audio_ref": str, "language": str }
  Output: { "segments": [{"text": str, "start_ms": int, "end_ms": int}], "language": str }

  GET /health -> { "status": "ok" }
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException
from faster_whisper import WhisperModel
from pydantic import BaseModel

logger = logging.getLogger("asr-engine")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Configuration (env vars)
# ---------------------------------------------------------------------------

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
ASR_MODEL = os.environ.get("ASR_MODEL", "base")
ASR_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")

# ---------------------------------------------------------------------------
# Global resources initialized at startup
# ---------------------------------------------------------------------------

whisper_model: WhisperModel | None = None
s3_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the whisper model and S3 client at startup."""
    global whisper_model, s3_client

    logger.info(
        "Loading faster-whisper model=%s compute_type=%s",
        ASR_MODEL,
        ASR_COMPUTE_TYPE,
    )
    whisper_model = WhisperModel(ASR_MODEL, compute_type=ASR_COMPUTE_TYPE)
    logger.info("Model loaded successfully")

    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    logger.info("S3 client initialized (endpoint=%s, bucket=%s)", MINIO_ENDPOINT, MINIO_BUCKET)

    yield

    # Cleanup (nothing to explicitly close for these resources)
    whisper_model = None
    s3_client = None


app = FastAPI(
    title="sauri ASR Engine",
    description="Local speech-to-text service powered by faster-whisper",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    """Request body for the /transcribe endpoint."""

    audio_ref: str
    language: str = "es-CO"


class Segment(BaseModel):
    """A transcription segment with timestamps."""

    text: str
    start_ms: int
    end_ms: int


class TranscribeResponse(BaseModel):
    """Response from the /transcribe endpoint."""

    segments: list[Segment]
    language: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download_audio_from_s3(audio_ref: str) -> str:
    """Download audio from S3/MinIO to a temporary file. Returns the temp file path."""
    assert s3_client is not None, "S3 client not initialized"

    # Determine file extension from the key for whisper compatibility
    ext = ""
    if "." in audio_ref:
        ext = "." + audio_ref.rsplit(".", 1)[-1]

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, tmp.name)
    except Exception as e:
        # Clean up temp file on download failure
        os.unlink(tmp.name)
        raise RuntimeError(f"Failed to download audio_ref={audio_ref!r} from bucket={MINIO_BUCKET!r}: {e}") from e

    return tmp.name


def _normalize_language_hint(language: str) -> str | None:
    """Convert language hint to a faster-whisper compatible language code.

    faster-whisper expects ISO 639-1 codes (e.g. 'es', 'en') or None for
    auto-detection. We strip region suffixes like '-CO' from 'es-CO'.
    """
    if not language:
        return None
    # Take the base language code (before any region separator)
    base = language.split("-")[0].strip().lower()
    return base if base else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    """Transcribe audio referenced by audio_ref.

    Downloads the audio from MinIO, runs faster-whisper, and returns
    segments with millisecond timestamps plus the detected language.
    """
    if whisper_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # 1. Download audio from object store
    try:
        audio_path = _download_audio_from_s3(request.audio_ref)
    except Exception as e:
        logger.error("Failed to download audio: %s", e)
        raise HTTPException(status_code=500, detail=f"Audio download failed: {e}")

    try:
        # 2. Run faster-whisper transcription
        language_hint = _normalize_language_hint(request.language)

        segments_iter, info = whisper_model.transcribe(
            audio_path,
            language=language_hint,
            beam_size=5,
            vad_filter=True,
        )

        # 3. Collect segments and convert timestamps to milliseconds
        segments: list[Segment] = []
        for segment in segments_iter:
            start_ms = int(segment.start * 1000)
            end_ms = int(segment.end * 1000)
            text = segment.text.strip()
            if text:  # Skip empty segments
                segments.append(Segment(text=text, start_ms=start_ms, end_ms=end_ms))

        # 4. Determine detected language
        detected_language = info.language if info.language else request.language

        return TranscribeResponse(
            segments=segments,
            language=detected_language,
        )

    except Exception as e:
        logger.error("Transcription failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    finally:
        # 5. Clean up temporary file
        try:
            os.unlink(audio_path)
        except OSError:
            pass


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
