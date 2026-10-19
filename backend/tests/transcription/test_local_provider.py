"""Tests for LocalProvider (local_provider.py).

# Feature: transcription-asr
Tasks: 4.2, 4.3, 4.4
"""

from __future__ import annotations

from typing import TypeGuard
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcription.asr_engine import TranscriptionOptions
from app.transcription.local_provider import LocalProvider

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

Segment = dict[str, str | int]


def _is_valid_segment(segment: dict[str, object]) -> TypeGuard[Segment]:
    text = segment["text"]
    start_ms = segment["start_ms"]
    end_ms = segment["end_ms"]
    return (
        isinstance(text, str)
        and isinstance(start_ms, int)
        and isinstance(end_ms, int)
        and end_ms >= start_ms
    )


segment_strategy: st.SearchStrategy[Segment] = st.fixed_dictionaries(
    {
        "text": st.text(min_size=1, max_size=100),
        "start_ms": st.integers(min_value=0, max_value=10_000_000),
        "end_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(_is_valid_segment)

segments_list_strategy: st.SearchStrategy[list[Segment]] = st.lists(
    segment_strategy, min_size=0, max_size=20
)


# ---------------------------------------------------------------------------
# Property 4: Faithful mapping of the local response to segments (Task 4.2)
# Feature: transcription-asr, Property 4: Faithful mapping of the local response
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------


@given(segments=segments_list_strategy)
@pytest.mark.asyncio
async def test_property_4_faithful_mapping_of_local_response(segments: list[Segment]) -> None:
    """Each segment in the response is faithfully mapped to TranscriptionSegment."""
    provider = LocalProvider(url="http://fake-asr:8001")
    options = TranscriptionOptions(preferred_language="es-CO")

    response_data = {"segments": segments, "language": "es"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.transcribe("audio/test.webm", options)

    assert len(result.segments) == len(segments)
    for seg_out, seg_in in zip(result.segments, segments, strict=True):
        assert seg_out.text == seg_in["text"]
        assert seg_out.start_ms == seg_in["start_ms"]
        assert seg_out.end_ms == seg_in["end_ms"]


# ---------------------------------------------------------------------------
# Property 6: Ascending order of segments (Task 4.3)
# Feature: transcription-asr, Property 6: Ascending order
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------


@given(segments=st.lists(segment_strategy, min_size=2, max_size=20))
@pytest.mark.asyncio
async def test_property_6_ascending_order_preserved(segments: list[Segment]) -> None:
    """Segments are returned in the order the service delivers them."""
    provider = LocalProvider(url="http://fake-asr:8001")
    options = TranscriptionOptions(preferred_language="es-CO")

    response_data = {"segments": segments, "language": "es"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.transcribe("audio/test.webm", options)

    # The segments preserve the order from the service response
    for i, seg in enumerate(result.segments):
        assert seg.start_ms == segments[i]["start_ms"]


# ---------------------------------------------------------------------------
# Example tests for the local provider (Task 4.4)
# Validates: Requirements 3.5, 3.6, 3.7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_http_error_propagates_exception() -> None:
    """Req 3.5: HTTP error from the service -> exception propagated with no partial segments."""
    provider = LocalProvider(url="http://fake-asr:8001")
    options = TranscriptionOptions(preferred_language="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=httpx.Request("POST", "http://fake-asr:8001/transcribe"),
        response=httpx.Response(500),
    )

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await provider.transcribe("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_timeout_propagates_exception() -> None:
    """Req 3.6: Timeout/unreachable -> exception propagated."""
    provider = LocalProvider(url="http://fake-asr:8001")
    options = TranscriptionOptions(preferred_language="es-CO")

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.ConnectTimeout):
            await provider.transcribe("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_response_without_segments_raises_valueerror() -> None:
    """Req 3.7: Response missing the 'segments' key -> ValueError."""
    provider = LocalProvider(url="http://fake-asr:8001")
    options = TranscriptionOptions(preferred_language="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"language": "es"}  # no 'segments'

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="segments"):
            await provider.transcribe("audio/test.webm", options)
