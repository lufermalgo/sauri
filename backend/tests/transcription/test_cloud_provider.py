"""Tests for CloudProvider (cloud_provider.py).

# Feature: transcription-asr
Tasks: 5.2, 5.3, 5.4
"""

from __future__ import annotations

import os
from typing import TypedDict, TypeGuard
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcription.asr_engine import TranscriptionOptions
from app.transcription.cloud_provider import CloudProvider, ExternalServiceError

# ---------------------------------------------------------------------------
# Property 3: Rejects an unencrypted endpoint (Task 5.2)
# Feature: transcription-asr, Property 3: Rejects an unencrypted endpoint
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------


@given(
    scheme=st.sampled_from(["http://", "ftp://", "ws://", ""]),
    host=st.from_regex(r"[a-z]{3,10}\.[a-z]{2,4}", fullmatch=True),
)
def test_property_3_rejects_unencrypted_endpoint(scheme: str, host: str) -> None:
    """Endpoint without HTTPS -> ValueError when constructing CloudProvider."""
    endpoint = scheme + host + "/transcribe"
    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": endpoint,
    }
    with patch.dict(os.environ, env, clear=False), pytest.raises(ValueError, match="HTTPS"):
        CloudProvider()


# ---------------------------------------------------------------------------
# Property 5: Validity of the result's segments (Task 5.3)
# Feature: transcription-asr, Property 5: Segment validity
# Validates: Requirements 4.5, 5.2, 5.3, 5.4
# ---------------------------------------------------------------------------

class SegmentData(TypedDict):
    text: str
    start_ms: int
    end_ms: int


def _has_valid_duration(segment: dict[str, object]) -> TypeGuard[SegmentData]:
    start_ms = segment.get("start_ms")
    end_ms = segment.get("end_ms")
    return isinstance(start_ms, int) and isinstance(end_ms, int) and end_ms >= start_ms


valid_segment_strategy: st.SearchStrategy[SegmentData] = st.fixed_dictionaries(
    {
        "text": st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
        "start_ms": st.integers(min_value=0, max_value=10_000_000),
        "end_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(_has_valid_duration)

invalid_segment_strategy: st.SearchStrategy[SegmentData] = st.one_of(
    # Empty text
    st.fixed_dictionaries(
        {"text": st.just(""), "start_ms": st.just(0), "end_ms": st.just(100)}
    ),
    # Negative start
    st.fixed_dictionaries(
        {"text": st.just("hola"), "start_ms": st.just(-1), "end_ms": st.just(100)}
    ),
    # end < start
    st.fixed_dictionaries(
        {"text": st.just("hola"), "start_ms": st.just(200), "end_ms": st.just(100)}
    ),
)


@given(
    valid_segs=st.lists(valid_segment_strategy, min_size=1, max_size=10),
    invalid_segs=st.lists(invalid_segment_strategy, min_size=0, max_size=5),
)
@pytest.mark.asyncio
async def test_property_5_only_valid_segments_in_result(
    valid_segs: list[SegmentData], invalid_segs: list[SegmentData]
) -> None:
    """Only segments with non-empty text, start>=0, end>=start are included."""
    all_segments = valid_segs + invalid_segs
    response_data = {"segments": all_segments}

    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        provider = CloudProvider()

    options = TranscriptionOptions(preferred_language="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcription.cloud_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.transcribe("audio/test.webm", options)

    # All returned segments must be valid
    for seg in result.segments:
        assert seg.text.strip()
        assert seg.start_ms >= 0
        assert seg.end_ms >= seg.start_ms

    # Count should match valid segments only
    assert len(result.segments) == len(valid_segs)


# ---------------------------------------------------------------------------
# Example/integration tests for the cloud provider (Task 5.4)
# Validates: Requirements 4.1, 4.3, 4.4, 4.6
# ---------------------------------------------------------------------------


def test_example_missing_api_key_raises_valueerror() -> None:
    """Req 4.4: Missing ASR_CLOUD_API_KEY -> ValueError."""
    env = {
        "ASR_CLOUD_API_KEY": "",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False), pytest.raises(ValueError, match="ASR_CLOUD_API_KEY"):
        CloudProvider()


@pytest.mark.asyncio
async def test_example_cloud_timeout_raises_service_error() -> None:
    """Req 4.6: Cloud service timeout -> ExternalServiceError."""
    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        provider = CloudProvider()

    options = TranscriptionOptions(preferred_language="es-CO")

    with patch("app.transcription.cloud_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ExternalServiceError, match="timeout"):
            await provider.transcribe("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_integration_https_and_auth_header() -> None:
    """Req 4.1, 4.3: Uses HTTPS and sends the Authorization Bearer header."""
    env = {
        "ASR_CLOUD_API_KEY": "sk-my-secret",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/v1/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        provider = CloudProvider()

    options = TranscriptionOptions(preferred_language="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "segments": [{"text": "hola", "start_ms": 0, "end_ms": 1000}]
    }

    with patch("app.transcription.cloud_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.transcribe("audio/test.webm", options)

        # Verify post was called with HTTPS endpoint and auth header
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/transcribe"
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-my-secret"

    assert len(result.segments) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("detected", ["en", None])
async def test_auto_requires_and_returns_detected_language(monkeypatch, detected):
    monkeypatch.setenv("ASR_CLOUD_API_KEY", "synthetic-key")
    monkeypatch.setenv("ASR_CLOUD_ENDPOINT", "https://example.test/transcribe")
    response = MagicMock()
    response.json.return_value = {
        "segments": [{"text": "synthetic", "start_ms": 0, "end_ms": 100}], "language": detected,
    }
    with patch("app.transcription.cloud_provider.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value.post.return_value = response
        if detected is None:
            with pytest.raises(ExternalServiceError, match="detected language"):
                await CloudProvider().transcribe("synthetic/ref", TranscriptionOptions("auto"))
        else:
            result = await CloudProvider().transcribe("synthetic/ref", TranscriptionOptions("auto"))
            assert result.language == detected
