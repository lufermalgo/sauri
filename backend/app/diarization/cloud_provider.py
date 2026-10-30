"""Cloud diarization provider with an encrypted channel (TLS).

Implements DiarizationEngine by sending audio to an external service over
HTTPS, guaranteeing encryption in transit (Req. 4.1, 4.2).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.diarization.diarization_engine import (
    DiarizationCapabilities,
    DiarizationEngine,
    DiarizationOptions,
    DiarizationResult,
    SpeakerSegment,
)


class ExternalServiceError(Exception):
    """Error indicating a failure of the external diarization service."""

    pass


class CloudProvider(DiarizationEngine):
    """Cloud diarization provider — TLS-encrypted channel (Req. 4.1, 4.2).

    Reads configuration from environment variables:
    - DIARIZATION_CLOUD_API_KEY: authentication key for the external service.
    - DIARIZATION_CLOUD_ENDPOINT: HTTPS URL of the diarization service.

    The endpoint MUST use HTTPS to guarantee encryption in transit.
    The API key MUST be present and non-empty.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("DIARIZATION_CLOUD_API_KEY", "").strip()
        self._endpoint = os.environ.get("DIARIZATION_CLOUD_ENDPOINT", "").strip()

        if not self._api_key:
            raise ValueError(
                "DIARIZATION_CLOUD_API_KEY must be defined and non-empty "
                "to authenticate with the external diarization service (Req. 4.4)"
            )

        if not self._endpoint.startswith("https://"):
            raise ValueError(
                "DIARIZATION_CLOUD_ENDPOINT must use HTTPS to guarantee "
                f"encryption in transit; unsupported scheme received: "
                f"'{self._endpoint}' (Req. 4.2)"
            )

    def capabilities(self) -> DiarizationCapabilities:
        """Declares capabilities: not local, cloud provider name."""
        return DiarizationCapabilities(is_local=False, provider_name="diarization-cloud")

    async def diarize(
        self, audio_ref: str, options: DiarizationOptions
    ) -> DiarizationResult:
        """Sends audio to the external service over an encrypted channel (HTTPS/TLS).

        Transmits with API key authentication and a 120s timeout (Req. 4.6).
        Validates each segment of the response before including it (Req. 4.5).

        Args:
            audio_ref: Reference to the audio object in the ObjectStore.
            options: Diarization configuration (duration, etc.).

        Returns:
            DiarizationResult with the validated diarized segments.

        Raises:
            ExternalServiceError: If the service doesn't respond within 120s,
                responds with an error, or doesn't return valid segments (Req. 4.6).
        """
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"audio_ref": audio_ref},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "The external diarization service did not respond within the "
                "120 second timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                f"The external diarization service responded with an error: "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.ConnectError, httpx.RequestError) as exc:
            raise ExternalServiceError(
                f"Could not connect to the external diarization service: {exc}"
            ) from exc

        segments = self._parse_and_validate_response(data, options.duration_ms)

        return DiarizationResult(
            segments=segments,
            speaker_count=len({s.raw_label for s in segments}),
        )

    def _parse_and_validate_response(
        self, data: dict[str, Any], duration_ms: int | None
    ) -> list[SpeakerSegment]:
        """Parses and validates the cloud service's JSON response (Req. 4.5).

        Only includes segments that satisfy:
        - non-empty raw_label (speaker)
        - start_ms integer >= 0
        - end_ms integer >= 0
        - end_ms >= start_ms
        - end_ms <= duration_ms (if the duration is known)

        Returns:
            List of validated SpeakerSegment (may be empty).
        """
        raw_segments = data.get("segments")
        if not isinstance(raw_segments, list):
            return []

        valid_segments: list[SpeakerSegment] = []
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue

            speaker = seg.get("speaker", "")
            start_ms = seg.get("start_ms")
            end_ms = seg.get("end_ms")

            # Validate non-empty raw_label
            if not isinstance(speaker, str) or not speaker.strip():
                continue

            # Validate start_ms and end_ms are integers >= 0
            if not isinstance(start_ms, int) or start_ms < 0:
                continue
            if not isinstance(end_ms, int) or end_ms < 0:
                continue

            # Validate end_ms >= start_ms
            if end_ms < start_ms:
                continue

            # Validate end_ms <= duration_ms if known
            if duration_ms is not None and end_ms > duration_ms:
                continue

            valid_segments.append(
                SpeakerSegment(
                    raw_label=speaker,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )

        return valid_segments
