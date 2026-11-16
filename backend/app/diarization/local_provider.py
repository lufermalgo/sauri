"""Local diarization provider — communicates with diar-engine.

Processes the audio recording without sending it outside sauri's
infrastructure (Req. 3.2). Talks to sauri's own diar-engine container over
internal HTTP (service-to-service within Docker).

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.diarization.diarization_engine import (
    DiarizationCapabilities,
    DiarizationEngine,
    DiarizationOptions,
    DiarizationResult,
    EngineContractError,
    EngineInfo,
    SpeakerSegment,
)
from app.engines.routing import ROUTE_HEADER, ProviderError, encode_route
from app.infra.recording_capability import create_recording_capability


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


def _provider_error(response: httpx.Response) -> ProviderError | None:
    """The classified failure a gateway reports for an external route (``{"error": {"code", ...}}``)."""
    try:
        error = response.json()["error"]
        code, retry_after = error["code"], error.get("retry_after_s")
        return ProviderError(code, retry_after_s=retry_after if type(retry_after) is int else None)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


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
        payload = {"audio_ref": audio_ref, "contract_version": 2}

        headers = _engine_auth_headers(audio_ref)
        if options.route is not None:
            headers[ROUTE_HEADER] = encode_route(options.route)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/diarize",
                json=payload,
                headers=headers,
                timeout=float(os.environ.get("DIARIZATION_TIMEOUT_SECONDS", "3600")),
            )
            if response.is_error and (failure := _provider_error(response)) is not None:
                raise failure
            response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict) or type(data.get("contract_version")) is not int or data["contract_version"] != 2:
            raise EngineContractError("Unsupported diarization contract_version; expected 2")

        # Req. 3.7: distinguish a missing "segments" key (error) from an empty list (valid)
        if "segments" not in data:
            raise ValueError(
                "Local diarization service response missing the 'segments' key: "
                "invalid structure"
            )

        info = data.get("engine")
        if not isinstance(info, dict) or any(
            not isinstance(info.get(key), str) or not info[key] for key in ("name", "model", "device")
        ):
            raise EngineContractError("Invalid diarization engine metadata")
        engine = EngineInfo(name=info["name"], model=info["model"], device=info["device"])

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
            engine=engine,
            contract_version=2,
            speaker_count=len({seg["speaker"] for seg in data["segments"]}),
            diagnostics=data["diagnostics"] if isinstance(data.get("diagnostics"), dict) else {},
        )
