"""Local diarization provider — communicates with diar-engine.

Processes the audio recording without sending it outside sauri's
infrastructure (Req. 3.2). Talks to sauri's own diar-engine container over
internal HTTP (service-to-service within Docker).

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import httpx

from app.diarization.diarization_engine import (
    DiarizationCapabilities,
    DiarizationEngine,
    DiarizationOptions,
    DiarizationResult,
    SpeakerSegment,
)


class LocalProvider(DiarizationEngine):
    """Local DiarizationEngine based on diar-engine (own container).

    Sends the audio reference to the local service for processing without
    the data ever leaving sauri's own infrastructure (Req. 3.2).
    """

    def __init__(self, url: str) -> None:
        """Initializes the local provider.

        Args:
            url: Base URL of the local diar-engine service
                 (e.g. http://localhost:8002 or http://diar-engine:8002).
        """
        self._url = url.rstrip("/")

    def capabilities(self) -> DiarizationCapabilities:
        """Declares the local diar-engine provider's capabilities."""
        return DiarizationCapabilities(is_local=True, provider_name="diar-engine-local")

    async def diarize(
        self, audio_ref: str, options: DiarizationOptions
    ) -> DiarizationResult:
        """Diarizes the audio by invoking the local diar-engine service.

        Sends a POST to {url}/diarize with the audio reference. The local
        service processes it without sending data to any external service
        (Req. 3.2).

        Args:
            audio_ref: Reference to the audio recording in the ObjectStore.
            options: Diarization configuration.

        Returns:
            DiarizationResult with segments and speaker_count.

        Raises:
            httpx.HTTPStatusError: If the service responds with an HTTP error (Req. 3.5).
            httpx.TimeoutException: If the service doesn't respond within 600s (Req. 3.6).
            httpx.ConnectError: If the service is unreachable (Req. 3.6).
            ValueError: If the response is missing the 'segments' key (Req. 3.7).
        """
        payload = {"audio_ref": audio_ref}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/diarize",
                json=payload,
                timeout=600.0,  # Diarization can take several minutes (Req. 3.1)
            )
            response.raise_for_status()

        data = response.json()

        # Req. 3.7: distinguish a missing "segments" key (error) from an empty list (valid)
        if "segments" not in data:
            raise ValueError(
                "Local diarization service response missing the 'segments' key: "
                "invalid structure"
            )

        segments = [
            SpeakerSegment(
                raw_label=seg["speaker"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
            )
            for seg in data["segments"]
        ]

        return DiarizationResult(
            segments=segments,
            speaker_count=len({seg["speaker"] for seg in data["segments"]}),
        )
