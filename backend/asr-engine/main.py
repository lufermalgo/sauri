"""ASR Engine — FastAPI service backed by faster-whisper.

Downloads audio from the object store (MinIO/S3) using the provided
audio_ref, transcribes it with faster-whisper, and returns segments
with millisecond timestamps.

Contract:
  POST /transcribe
  Input: audio_ref, language, contract_version=2.
  Output: contract_version=2, segments, words, language, engine, diagnostics.

  GET /health -> { "status": "ok" }
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Literal

import boto3
from asr_config import default_language, server_budget
from botocore.config import Config
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from faster_whisper import WhisperModel  # type: ignore[import-not-found]
from pydantic import BaseModel, Field
from whisper_words import repair_word_timing

logger = logging.getLogger("asr-engine")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Configuration (env vars)
# ---------------------------------------------------------------------------

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
ASR_MODEL = os.environ.get("ASR_MODEL", "base")
ASR_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")

# ---------------------------------------------------------------------------
# Global resources initialized at startup
# ---------------------------------------------------------------------------

whisper_model: WhisperModel | None = None
s3_client = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the whisper model and S3 client at startup."""
    global whisper_model, s3_client
    default_language()
    server_budget()

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
    language: str = Field(default_factory=default_language)
    contract_version: Literal[2] = 2


class Segment(BaseModel):
    """A transcription segment with timestamps."""

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

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp_path = tmp.name

    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, tmp_path)
    except Exception as e:
        # Clean up temp file on download failure
        os.unlink(tmp_path)
        raise RuntimeError("Failed to download audio") from e

    return tmp_path


def _normalize_language_hint(language: str) -> str | None:
    """Convert language hint to a faster-whisper compatible language code.

    faster-whisper expects ISO 639-1 codes (e.g. 'es', 'en') or None for
    auto-detection. Region suffixes are stripped.
    """
    if not language:
        return None
    # Take the base language code (before any region separator)
    base = language.split("-")[0].strip().lower()
    return base if base and base != "auto" else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    """Transcribe audio referenced by audio_ref.

    Downloads the audio from MinIO, runs faster-whisper, and returns
    segments with millisecond timestamps plus the detected language.
    """
    try:
        return await asyncio.wait_for(run_in_threadpool(_transcribe_audio, request), timeout=server_budget())
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="engine_failed") from exc


def _transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    if whisper_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # 1. Download audio from object store
    try:
        audio_path = _download_audio_from_s3(request.audio_ref)
    except Exception as e:
        logger.error("Audio download failed")
        raise HTTPException(status_code=500, detail="engine_failed") from e

    try:
        # 2. Run faster-whisper transcription
        started = time.monotonic()
        language_hint = _normalize_language_hint(request.language)

        segments_iter, info = whisper_model.transcribe(
            audio_path,
            language=language_hint,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )

        # 3. Collect segments and convert timestamps to milliseconds
        segments: list[Segment] = []
        words: list[Word] = []
        previous_valid_end = 0
        inverted_words = 0
        for segment in segments_iter:
            start_ms = int(segment.start * 1000)
            end_ms = int(segment.end * 1000)
            text = segment.text.strip()
            if text:  # Skip empty segments
                if not segment.words:
                    raise HTTPException(status_code=500, detail="no_word_timestamps")
                for word in segment.words:
                    start, end, repaired = repair_word_timing(
                        round(word.start * 1000), round(word.end * 1000), round(info.duration * 1000),
                        previous_valid_end,
                    )
                    inverted_words += int(repaired)
                    if not repaired:
                        previous_valid_end = end
                    words.append(Word(text=word.word, start_ms=start, end_ms=end,
                                      probability=word.probability, timing_repaired=repaired))
                segments.append(Segment(text=text, start_ms=start_ms, end_ms=end_ms))

        # 4. Determine detected language
        detected_language = info.language if info.language else request.language

        if not detected_language or detected_language == "auto":
            raise ValueError("Missing detected language")
        return TranscribeResponse(
            words=words,
            engine=EngineInfo(name="faster-whisper", model=ASR_MODEL, device=str(whisper_model.model.device)),
            diagnostics={"audio_ms": round(info.duration * 1000), "inverted_words": inverted_words,
                         "stage_ms": {"inference": round((time.monotonic() - started) * 1000)}},
            segments=segments,
            language=detected_language,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Transcription failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="engine_failed") from e

    finally:
        # 5. Clean up temporary file
        with suppress(OSError):
            os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
