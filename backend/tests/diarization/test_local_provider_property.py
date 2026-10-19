"""Property tests for the diarization LocalProvider.

# Feature: speaker-identification, Property 4: Faithful mapping of the local response to SpeakerSegments
"""

from __future__ import annotations

from typing import TypedDict, TypeGuard, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.diarization_engine import DiarizationOptions
from app.diarization.local_provider import LocalProvider

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class Segment(TypedDict):
    speaker: str
    start_ms: int
    end_ms: int


def _is_valid_segment(segment: dict[str, object]) -> TypeGuard[Segment]:
    start_ms = segment.get("start_ms")
    end_ms = segment.get("end_ms")
    return (
        isinstance(segment.get("speaker"), str)
        and isinstance(start_ms, int)
        and isinstance(end_ms, int)
        and end_ms >= start_ms
    )


_raw_segment_strategy: st.SearchStrategy[dict[str, object]] = cast(
    st.SearchStrategy[dict[str, object]],
    st.fixed_dictionaries(
        {
            "speaker": st.text(min_size=1, max_size=50),
            "start_ms": st.integers(min_value=0, max_value=10_000_000),
            "end_ms": st.integers(min_value=0, max_value=10_000_000),
        }
    ),
)
segment_strategy: st.SearchStrategy[Segment] = cast(
    st.SearchStrategy[Segment], _raw_segment_strategy.filter(_is_valid_segment)
)

segments_list_strategy: st.SearchStrategy[list[Segment]] = st.lists(
    segment_strategy, min_size=0, max_size=20
)


# ---------------------------------------------------------------------------
# Property 4: Faithful mapping of the local response to SpeakerSegments
# Feature: speaker-identification, Property 4: Faithful mapping of the local response to SpeakerSegments
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segments=segments_list_strategy)
@pytest.mark.asyncio
async def test_property_4_faithful_mapping_of_local_diarization_response(
    segments: list[Segment],
) -> None:
    """For any valid response with N elements {speaker, start_ms, end_ms},
    LocalProvider produces exactly N SpeakerSegment preserving
    raw_label=speaker, start_ms=start_ms, end_ms=end_ms in the same order.

    **Validates: Requirements 3.4**
    """
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    response_data = {
        "segments": segments,
        "num_speakers": len({s["speaker"] for s in segments}),
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.diarize("audio/test.webm", options)

    # Exactly N segments produced
    assert len(result.segments) == len(segments)

    # Faithful preservation of each field (DiarizationResult orders by start_ms
    # per Property 6 / Req. 5.1, so we compare after sorting the input)
    expected_tuples = sorted(
        [(s["speaker"], s["start_ms"], s["end_ms"]) for s in segments],
        key=lambda t: t[1],
    )
    actual_tuples = [
        (s.raw_label, s.start_ms, s.end_ms) for s in result.segments
    ]
    assert actual_tuples == expected_tuples


# ---------------------------------------------------------------------------
# Example tests for the diarization LocalProvider (Task 5.2)
# Validates: Requirements 3.5, 3.6, 3.7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_http_500_error_produces_no_partial_segments() -> None:
    """Req 3.5: HTTP error (status 500) -> the provider signals failure with no partial segments."""
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=httpx.Request("POST", "http://fake-diar-engine:8002/diarize"),
        response=httpx.Response(500),
    )

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await provider.diarize("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_timeout_signals_failure() -> None:
    """Req 3.6: Timeout (httpx.TimeoutException) -> the provider signals failure."""
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.TimeoutException):
            await provider.diarize("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_connect_error_signals_failure() -> None:
    """Req 3.6: ConnectError (httpx.ConnectError) -> the provider signals failure."""
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.ConnectError):
            await provider.diarize("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_response_without_segments_raises_valueerror() -> None:
    """Req 3.7: Response missing the 'segments' key -> ValueError (invalid structure)."""
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    # Response missing the "segments" key — invalid structure
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"num_speakers": 2}

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="segments"):
            await provider.diarize("audio/test.webm", options)


@pytest.mark.asyncio
async def test_example_empty_segments_is_a_valid_result() -> None:
    """Req 3.7: `segments: []` (empty list) is a valid result — doesn't raise.
    This distinguishes a missing key (ValueError) from a result with no speakers.
    """
    provider = LocalProvider(url="http://fake-diar-engine:8002")
    options = DiarizationOptions()

    # segments: [] is a valid response (no speakers detected)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"segments": [], "num_speakers": 0}

    with patch(
        "app.diarization.local_provider.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await provider.diarize("audio/test.webm", options)

    # Doesn't raise and produces zero segments
    assert result.segments == []
