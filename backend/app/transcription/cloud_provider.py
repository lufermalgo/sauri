"""Cloud transcription provider with an encrypted channel (TLS).

Implements ASREngine by sending audio to an external ASR service over
HTTPS, guaranteeing encryption in transit (Req. 4.1, 4.2).
"""

from __future__ import annotations

import os

import httpx

from app.transcription.asr_engine import (
    ASRCapabilities,
    ASREngine,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionSegment,
)


class ExternalServiceError(Exception):
    """Error indicating a failure of the external ASR service."""

    pass


class CloudProvider(ASREngine):
    """Cloud ASR provider — TLS-encrypted channel (Req. 4.1, 4.2).

    Reads configuration from environment variables:
    - ASR_CLOUD_API_KEY: authentication key for the external service.
    - ASR_CLOUD_ENDPOINT: HTTPS URL of the transcription service.

    The endpoint MUST use HTTPS to guarantee encryption in transit.
    The API key MUST be present and non-empty.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("ASR_CLOUD_API_KEY", "").strip()
        self._endpoint = os.environ.get("ASR_CLOUD_ENDPOINT", "").strip()

        if not self._api_key:
            raise ValueError(
                "ASR_CLOUD_API_KEY must be defined and non-empty "
                "to authenticate with the external ASR service (Req. 4.4)"
            )

        if not self._endpoint.startswith("https://"):
            raise ValueError(
                "ASR_CLOUD_ENDPOINT must use HTTPS to guarantee "
                f"encryption in transit; unsupported scheme received: "
                f"'{self._endpoint}' (Req. 4.2)"
            )

    def capabilities(self) -> ASRCapabilities:
        """Declares capabilities: supports turns, not local."""
        return ASRCapabilities(supports_turns=True, is_local=False)

    async def transcribe(
        self, audio_ref: str, options: TranscriptionOptions
    ) -> TranscriptionResult:
        """Sends audio to the external service over an encrypted channel (HTTPS/TLS).

        Transmits with API key authentication and a 30s timeout. Validates
        each segment of the response before including it.

        Args:
            audio_ref: Reference to the audio object in the ObjectStore.
            options: Transcription configuration (language, etc.).

        Returns:
            TranscriptionResult with the validated transcribed segments.

        Raises:
            ExternalServiceError: If the service doesn't respond within 30s,
                responds with an error, or doesn't return valid segments.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "audio_ref": audio_ref,
                        "language": options.preferred_language,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise ExternalServiceError(
                "The external ASR service did not respond within the "
                "30 second timeout"
            )
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                f"The external ASR service responded with an error: "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.ConnectError, httpx.RequestError) as exc:
            raise ExternalServiceError(
                f"Could not connect to the external ASR service: {exc}"
            ) from exc

        segments = self._parse_and_validate_response(data)

        if not segments:
            raise ExternalServiceError(
                "The external ASR service did not return valid segments"
            )

        return TranscriptionResult(
            segments=segments,
            language=options.preferred_language,
            supports_turns=True,
        )

    def _parse_and_validate_response(
        self, data: dict
    ) -> list[TranscriptionSegment]:
        """Parses and validates the cloud service's JSON response.

        Only includes segments that satisfy:
        - non-empty text
        - start_ms integer >= 0
        - end_ms integer >= 0
        - end_ms >= start_ms

        Returns:
            List of validated TranscriptionSegment (may be empty if no
            segment passes validation).
        """
        raw_segments = data.get("segments")
        if not isinstance(raw_segments, list):
            return []

        valid_segments: list[TranscriptionSegment] = []
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue

            text = seg.get("text", "")
            start_ms = seg.get("start_ms")
            end_ms = seg.get("end_ms")

            # Validate non-empty text
            if not isinstance(text, str) or not text.strip():
                continue

            # Validate start_ms and end_ms are integers >= 0
            if not isinstance(start_ms, int) or start_ms < 0:
                continue
            if not isinstance(end_ms, int) or end_ms < 0:
                continue

            # Validate end_ms >= start_ms
            if end_ms < start_ms:
                continue

            valid_segments.append(
                TranscriptionSegment(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )

        return valid_segments
