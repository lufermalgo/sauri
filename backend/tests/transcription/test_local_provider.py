"""Tests for LocalProvider (local_provider.py).

# Feature: transcription-asr
Tasks: 4.2, 4.3, 4.4
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import TypeGuard
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcription.asr_engine import EngineContractError, TranscriptionOptions
from app.transcription.local_provider import LocalProvider


def v2(**fields):
    return {"contract_version": 2, "words": [], "diagnostics": {"inverted_words": 0},
            "engine": {"name": "whisper.cpp", "model": "turbo", "device": "metal"}, **fields}


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

    response_data = v2(segments=segments, language="es")

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

    response_data = v2(segments=segments, language="es")

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
    mock_response.json.return_value = v2(language="es")  # no 'segments'

    with patch("app.transcription.local_provider.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="segments"):
            await provider.transcribe("audio/test.webm", options)


@pytest.mark.asyncio
async def test_local_provider_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_TIMEOUT_SECONDS", "3600")
    provider = LocalProvider(url="http://fake-asr:8001")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = v2(segments=[], language="es")

    with patch("app.transcription.local_provider.httpx.AsyncClient") as client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        client_class.return_value = mock_client
        await provider.transcribe(
            "recordings/synthetic.wav", TranscriptionOptions(preferred_language="es-CO")
        )

    assert mock_client.post.call_args.kwargs["timeout"] == 3600.0


@pytest.mark.asyncio
async def test_local_provider_sends_bearer_token_from_secret_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "engine_token"
    token_file.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token_file))
    capability_key_file = tmp_path / "recording_capability_key"
    capability_key_file.write_bytes(b"synthetic-capability-secret")
    monkeypatch.setenv("SAURI_RECORDING_CAPABILITY_KEY_FILE", str(capability_key_file))
    provider = LocalProvider(url="http://fake-asr:8001")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = v2(segments=[], language="es")

    with patch("app.transcription.local_provider.httpx.AsyncClient") as client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        client_class.return_value = mock_client
        await provider.transcribe(
            "recordings/synthetic.wav", TranscriptionOptions(preferred_language="es-CO")
        )

    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer synthetic-token"
    expiry_text, signature = headers["X-Sauri-Recording-Capability"].split(".")
    message = f"recordings/synthetic.wav\n{expiry_text}".encode()
    expected = hmac.new(b"synthetic-capability-secret", message, hashlib.sha256).hexdigest()
    assert signature == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, 1, "2", 2.0, True, 3])
async def test_rejects_incompatible_contract_version(version):
    response = MagicMock()
    response.json.return_value = v2(segments=[], language="es", contract_version=version)
    with patch("app.transcription.local_provider.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value.post.return_value = response
        with pytest.raises(EngineContractError, match="contract_version"):
            await LocalProvider("http://test").transcribe("recordings/a.wav", TranscriptionOptions())


@pytest.mark.asyncio
async def test_exposes_v2_words_engine_and_diagnostics():
    response = MagicMock()
    word = {"text": "hello", "start_ms": 5, "end_ms": 5, "probability": 0.8, "timing_repaired": True}
    response.json.return_value = v2(segments=[], words=[word], language="en",
                                   diagnostics={"inverted_words": 1, "stage_ms": {"inference": 10}})
    with patch("app.transcription.local_provider.httpx.AsyncClient") as cls:
        post = cls.return_value.__aenter__.return_value.post
        post.return_value = response
        result = await LocalProvider("http://test").transcribe(
            "recordings/a.wav", TranscriptionOptions(preferred_language="auto"))
    assert post.call_args.kwargs["json"]["contract_version"] == 2
    assert result.words[0].text == "hello" and result.words[0].timing_repaired
    assert result.words[0].probability == 0.8
    assert result.engine.name == "whisper.cpp" and result.contract_version == 2
    assert result.inverted_words == 1 and result.diagnostics["stage_ms"] == {"inference": 10}
    assert result.language == "en"


@pytest.mark.asyncio
@pytest.mark.parametrize(("start", "end"), [(1.0, 2), (1, "2"), (True, 2), (2, 1), (-1, 2), (None, 2)])
async def test_rejects_invalid_word_timestamps(start, end):
    response = MagicMock()
    response.json.return_value = v2(segments=[], language="es",
                                   words=[{"text": "word", "start_ms": start, "end_ms": end}])
    with patch("app.transcription.local_provider.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value.post.return_value = response
        with pytest.raises(EngineContractError, match="timestamps"):
            await LocalProvider("http://test").transcribe("recordings/a.wav", TranscriptionOptions())
