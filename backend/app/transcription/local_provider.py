"""Local transcription provider based on faster-whisper.

Processes the audio recording without sending it to an external service
(Req. 5.3). Talks to sauri's own asr-engine container over internal HTTP
(no TLS, service-to-service within Docker).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.infra.recording_capability import create_recording_capability
from app.transcription.asr_engine import (
    ASRCapabilities,
    ASREngine,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionSegment,
    WordInterval,
)


def _engine_auth_headers(audio_ref: str) -> dict[str, str]:
    token_file = os.environ.get("SAURI_ENGINE_TOKEN_FILE")
    if not token_file:
        return {}
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers["X-Sauri-Recording-Capability"] = create_recording_capability(audio_ref)
    return headers


class LocalProvider(ASREngine):
    """Local ASREngine based on faster-whisper (asr-engine container).

    Sends the audio reference to the local service for processing without
    the data ever leaving sauri's own infrastructure.
    """

    def __init__(self, url: str) -> None:
        """Initializes the local provider.

        Args:
            url: Base URL of the local asr-engine service
                 (e.g. http://localhost:8001 or http://asr-engine:8001).
        """
        self._url = url.rstrip("/")

    def capabilities(self) -> ASRCapabilities:
        """Declares the local faster-whisper provider's capabilities."""
        return ASRCapabilities(supports_turns=True, is_local=True)

    async def transcribe(
        self, audio_ref: str, options: TranscriptionOptions
    ) -> TranscriptionResult:
        """Transcribes the audio by invoking the local asr-engine service.

        Sends a POST to {url}/transcribe with the audio reference and the
        preferred language. The local service processes it without sending
        data to any external service (Req. 5.3).

        Args:
            audio_ref: Reference to the audio recording in the ObjectStore.
            options: Transcription configuration (preferred language).

        Returns:
            TranscriptionResult with segments, language, and turn support.

        Raises:
            httpx.HTTPStatusError: If the service responds with an HTTP error.
        """
        payload = {
            "audio_ref": audio_ref,
            "language": options.preferred_language,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/transcribe",
                json=payload,
                headers=_engine_auth_headers(audio_ref),
                timeout=float(os.environ.get("ASR_TIMEOUT_SECONDS", "3600")),
            )
            response.raise_for_status()

        data = response.json()

        if "segments" not in data:
            raise ValueError(
                "Local ASR service response missing the 'segments' key: "
                "invalid structure"
            )

        segments = [
            TranscriptionSegment(
                text=seg["text"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
                words=[WordInterval(text=w["text"], start_ms=w["start_ms"], end_ms=w["end_ms"])
                       for w in (seg.get("alignment") or [])],
            )
            for seg in data["segments"]
        ]

        return TranscriptionResult(
            segments=segments,
            language=data.get("language", options.preferred_language),
            supports_turns=True,
        )
