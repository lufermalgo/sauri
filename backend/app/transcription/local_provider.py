"""Local transcription provider for the versioned ASR HTTP service.

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
    EngineContractError,
    EngineInfo,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
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
    """Local ASREngine for native whisper.cpp or container faster-whisper.

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
        """Declares the local ASR provider's capabilities."""
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
            "contract_version": 2,
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

        if not isinstance(data, dict) or type(data.get("contract_version")) is not int or data["contract_version"] != 2:
            raise EngineContractError("Unsupported ASR contract_version; expected 2")
        info = data.get("engine")
        if not isinstance(info, dict) or any(
            not isinstance(info.get(key), str) or not info[key] for key in ("name", "model", "device")
        ):
            raise EngineContractError("Invalid ASR engine metadata")
        if not isinstance(data.get("words"), list) or not isinstance(data.get("diagnostics"), dict):
            raise EngineContractError("Invalid ASR words or diagnostics")
        if not isinstance(data.get("language"), str) or not data["language"] or data["language"] == "auto":
            raise EngineContractError("Invalid ASR detected language")

        if "segments" not in data:
            raise ValueError(
                "Local ASR service response missing the 'segments' key: "
                "invalid structure"
            )

        try:
            segments = [
                TranscriptionSegment(
                    text=seg["text"],
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                )
                for seg in data["segments"]
            ]
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid ASR segments") from exc

        for word in data["words"]:
            if not isinstance(word, dict) or any(
                type(word.get(key)) is not int for key in ("start_ms", "end_ms")
            ) or word["start_ms"] < 0 or word["start_ms"] > word["end_ms"]:
                raise EngineContractError("Invalid ASR word timestamps")
        try:
            words = [TranscriptionWord(**word) for word in data["words"]]
        except (TypeError, KeyError) as exc:
            raise EngineContractError("Invalid ASR words") from exc
        inverted_words = data["diagnostics"].get("inverted_words", 0)
        if type(inverted_words) is not int or inverted_words < 0:
            raise EngineContractError("Invalid ASR inverted_words")

        return TranscriptionResult(
            words=words,
            engine=EngineInfo(name=info["name"], model=info["model"], device=info["device"]),
            diagnostics=data["diagnostics"],
            inverted_words=inverted_words,
            segments=segments,
            language=data.get("language", options.preferred_language),
            supports_turns=True,
        )
