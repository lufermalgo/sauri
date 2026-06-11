"""ASR Engine — Placeholder FastAPI service for faster-whisper.

This is a STUB that defines the contract (input/output) for the local
ASR engine. The real implementation will integrate faster-whisper for
actual speech-to-text processing.

Contract:
  POST /transcribe
  Input:  { "audio_ref": str, "language": str }
  Output: { "segments": [{"text": str, "start_ms": int, "end_ms": int}], "language": str }
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="sauri ASR Engine",
    description="Local speech-to-text service (faster-whisper placeholder)",
    version="0.1.0",
)


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


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    """Transcribe audio referenced by audio_ref.

    PLACEHOLDER: Returns sample segments. The real implementation will
    load the audio from the object store and process it with faster-whisper.
    """
    # Stub response — demonstrates the contract
    sample_segments = [
        Segment(
            text="Bienvenidos a la reunión de hoy.",
            start_ms=0,
            end_ms=3500,
        ),
        Segment(
            text="Vamos a revisar los resultados del trimestre.",
            start_ms=3500,
            end_ms=7200,
        ),
    ]

    return TranscribeResponse(
        segments=sample_segments,
        language=request.language,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
