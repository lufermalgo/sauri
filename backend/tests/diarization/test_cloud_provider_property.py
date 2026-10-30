# Feature: speaker-identification, Property 3: CloudProvider rejects an unencrypted endpoint
"""Property test: CloudProvider rejects endpoints without HTTPS.

**Validates: Requirements 4.2**

For any DIARIZATION_CLOUD_ENDPOINT whose scheme isn't https,
CloudProvider initialization fails with a ValueError indicating the
unsupported scheme, without transmitting audio.
"""

from __future__ import annotations

import os
import string
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------

# Schemes other than "https" with known and generated variants
_scheme_known = st.sampled_from(["http://", "ftp://", "ws://", "wss://", "file://", ""])
_scheme_random = st.text(
    alphabet=string.ascii_lowercase + string.digits + "+-.",
    min_size=1,
    max_size=10,
).filter(lambda s: s != "https").map(lambda s: f"{s}://")

_non_https_scheme = st.one_of(_scheme_known, _scheme_random)

_host = st.from_regex(r"[a-z]{3,10}\.[a-z]{2,5}", fullmatch=True)

# URLs with a non-https scheme
_non_https_endpoint = st.builds(
    lambda scheme, host: f"{scheme}{host}/diarize",
    _non_https_scheme,
    _host,
)

# Strings with no scheme (bare strings)
_bare_endpoint = st.text(
    alphabet=string.ascii_letters + string.digits + ".-_/",
    min_size=1,
    max_size=40,
).filter(lambda s: not s.startswith("https://"))

# Combined strategy for non-HTTPS endpoints
_unencrypted_endpoint = st.one_of(_non_https_endpoint, _bare_endpoint)

# Valid API key (non-empty, required so init doesn't fail on the key first)
_valid_api_key = st.text(
    alphabet=string.ascii_letters + string.digits + "-_",
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(endpoint=_unencrypted_endpoint, api_key=_valid_api_key)
def test_property_3_rejects_unencrypted_endpoint(endpoint: str, api_key: str) -> None:
    """Property 3: CloudProvider rejects endpoints without HTTPS.

    Validates: Requirements 4.2

    For any DIARIZATION_CLOUD_ENDPOINT whose scheme isn't https,
    CloudProvider initialization fails with a ValueError indicating the
    unsupported scheme, without transmitting audio.
    """
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": endpoint,
        "DIARIZATION_CLOUD_API_KEY": api_key,
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider

        with pytest.raises(ValueError) as exc_info:
            CloudProvider()

        # The message must indicate the unsupported scheme
        message = str(exc_info.value).lower()
        assert "https" in message or "scheme" in message or "encryption" in message, (
            f"The ValueError doesn't indicate the unsupported scheme: {exc_info.value!r}"
        )


# Feature: speaker-identification, Property 5: Validity of the result's SpeakerSegments
# ---------------------------------------------------------------------------
# Property test 5: Validity of the result's SpeakerSegments
#
# **Validates: Requirements 4.5, 5.2, 5.3, 5.4**
#
# For any DiarizationResult produced by CloudProvider over an audio
# recording of duration D, every SpeakerSegment satisfies:
# start_ms and end_ms are integers, start_ms >= 0, end_ms >= start_ms,
# end_ms <= D, and raw_label is non-empty.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Generation strategies for Property 5
# ---------------------------------------------------------------------------

# Total recording duration: between 1000 ms and 10_000_000 ms
_duration_ms_strategy = st.integers(min_value=1000, max_value=10_000_000)

# Non-empty raw label
_raw_label_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + "_",
    min_size=1,
    max_size=30,
)


@st.composite
def _valid_segment_for_duration(
    draw: Any, duration_ms: int
) -> dict[str, int | str]:
    """Generates a valid segment respecting the duration_ms constraints."""
    speaker = draw(_raw_label_strategy)
    start_ms = draw(st.integers(min_value=0, max_value=max(0, duration_ms - 1)))
    end_ms = draw(st.integers(min_value=start_ms, max_value=duration_ms))
    return {"speaker": speaker, "start_ms": start_ms, "end_ms": end_ms}


@st.composite
def _cloud_response_with_valid_segments(
    draw: Any,
) -> tuple[int, list[dict[str, int | str]]]:
    """Generates a duration_ms and valid segments from the external service."""
    duration = draw(_duration_ms_strategy)
    num_segments = draw(st.integers(min_value=1, max_value=20))
    segments = [draw(_valid_segment_for_duration(duration)) for _ in range(num_segments)]
    return duration, segments


# ---------------------------------------------------------------------------
# Property test 5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=_cloud_response_with_valid_segments())
async def test_property_5_speaker_segment_validity(
    data: tuple[int, list[dict[str, int | str]]],
) -> None:
    """Property 5: Validity of the result's SpeakerSegments.

    Validates: Requirements 4.5, 5.2, 5.3, 5.4

    For any valid response from the external service with segments and a
    duration_ms for the recording, CloudProvider produces SpeakerSegment
    where:
    - start_ms and end_ms are integers
    - start_ms >= 0
    - end_ms >= start_ms
    - end_ms <= duration_ms
    - raw_label is a non-empty string
    """
    duration, raw_segments = data

    # Build the simulated JSON response from the external service
    response_json = {
        "segments": raw_segments,
        "num_speakers": len(set(s["speaker"] for s in raw_segments)),
    }

    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_json

    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }

    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider
        from app.diarization.diarization_engine import DiarizationOptions

        provider = CloudProvider()

        # Patch httpx.AsyncClient to return the simulated response
        with patch(
            "app.diarization.cloud_provider.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            options = DiarizationOptions(duration_ms=duration)
            result = await provider.diarize("audio/test.wav", options)

    # Verify the property for each segment of the result
    assert len(result.segments) > 0, "There must be at least one segment"

    for seg in result.segments:
        # start_ms is an int
        assert isinstance(seg.start_ms, int), (
            f"start_ms must be int, got {type(seg.start_ms)}"
        )
        # end_ms is an int
        assert isinstance(seg.end_ms, int), (
            f"end_ms must be int, got {type(seg.end_ms)}"
        )
        # start_ms >= 0
        assert seg.start_ms >= 0, (
            f"start_ms must be >= 0, got {seg.start_ms}"
        )
        # end_ms >= start_ms
        assert seg.end_ms >= seg.start_ms, (
            f"end_ms ({seg.end_ms}) must be >= start_ms ({seg.start_ms})"
        )
        # end_ms <= duration_ms
        assert seg.end_ms <= duration, (
            f"end_ms ({seg.end_ms}) must be <= duration_ms ({duration})"
        )
        # raw_label is a non-empty string
        assert isinstance(seg.raw_label, str), (
            f"raw_label must be str, got {type(seg.raw_label)}"
        )
        assert len(seg.raw_label) > 0, (
            "raw_label must not be empty"
        )


# ---------------------------------------------------------------------------
# Example tests for the diarization CloudProvider (Task 6.3)
# Validates: Requirements 4.4, 4.6
# ---------------------------------------------------------------------------


def test_example_missing_api_key_raises_valueerror() -> None:
    """Req 4.4: Missing DIARIZATION_CLOUD_API_KEY -> ValueError."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_CLOUD_API_KEY", None)
        from app.diarization.cloud_provider import CloudProvider

        with pytest.raises(ValueError, match="DIARIZATION_CLOUD_API_KEY"):
            CloudProvider()


def test_example_empty_api_key_raises_valueerror() -> None:
    """Req 4.4: Empty DIARIZATION_CLOUD_API_KEY -> ValueError."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "   ",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider

        with pytest.raises(ValueError, match="DIARIZATION_CLOUD_API_KEY"):
            CloudProvider()


@pytest.mark.asyncio
async def test_example_120s_timeout_raises_external_service_error() -> None:
    """Req 4.6: 120s timeout -> ExternalServiceError, preserving the audio."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider, ExternalServiceError
        from app.diarization.diarization_engine import DiarizationOptions

        provider = CloudProvider()

        with patch(
            "app.diarization.cloud_provider.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ExternalServiceError, match="120"):
                await provider.diarize("audio/test.wav", DiarizationOptions())


@pytest.mark.asyncio
async def test_example_http_error_raises_external_service_error() -> None:
    """Req 4.6: HTTP error from the external service -> ExternalServiceError."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider, ExternalServiceError
        from app.diarization.diarization_engine import DiarizationOptions

        provider = CloudProvider()

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable",
            request=httpx.Request("POST", "https://api.example.com/diarize"),
            response=httpx.Response(503),
        )

        with patch(
            "app.diarization.cloud_provider.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ExternalServiceError, match="503"):
                await provider.diarize("audio/test.wav", DiarizationOptions())


@pytest.mark.asyncio
async def test_example_response_without_valid_segments_returns_empty() -> None:
    """Req 4.6: Response with no valid segments -> DiarizationResult with zero segments."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarization.cloud_provider import CloudProvider
        from app.diarization.diarization_engine import DiarizationOptions

        provider = CloudProvider()

        # Response with invalid segments (start_ms > end_ms)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "segments": [{"speaker": "", "start_ms": 100, "end_ms": 50}],
            "num_speakers": 0,
        }

        with patch(
            "app.diarization.cloud_provider.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider.diarize("audio/test.wav", DiarizationOptions())

    assert result.segments == []
    assert result.speaker_count == 0
