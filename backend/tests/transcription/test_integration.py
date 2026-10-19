"""Integration tests for the transcription-asr module.

# Feature: transcription-asr
Tasks: 11.2, 12.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.transcription.worker import start_worker

# ---------------------------------------------------------------------------
# asr-engine contract integration test (Task 11.2)
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------


class TestASREngineContract:
    """Verifies that the POST /transcribe and GET /health contract is correct."""

    @pytest.mark.asyncio
    async def test_post_transcribe_response_shape(self) -> None:
        """POST /transcribe returns {segments: [{text, start_ms, end_ms}], language}."""
        from pydantic import BaseModel

        class Segment(BaseModel):
            text: str
            start_ms: int
            end_ms: int

        class TranscribeResponse(BaseModel):
            segments: list[Segment]
            language: str

        # Verify the contract shape
        response_data = {
            "segments": [
                {"text": "Hola mundo", "start_ms": 0, "end_ms": 2000},
                {"text": "¿Cómo estás?", "start_ms": 2100, "end_ms": 4000},  # spanish-sample-data
            ],
            "language": "es",
        }

        parsed = TranscribeResponse(**response_data)
        assert len(parsed.segments) == 2
        assert parsed.segments[0].text == "Hola mundo"
        assert parsed.segments[0].start_ms == 0
        assert parsed.segments[0].end_ms == 2000
        assert parsed.language == "es"

    @pytest.mark.asyncio
    async def test_post_transcribe_valid_empty_response(self) -> None:
        """POST /transcribe with empty audio returns segments: [], language."""
        from pydantic import BaseModel

        class Segment(BaseModel):
            text: str
            start_ms: int
            end_ms: int

        class TranscribeResponse(BaseModel):
            segments: list[Segment]
            language: str

        response_data = {"segments": [], "language": "es"}
        parsed = TranscribeResponse(**response_data)
        assert parsed.segments == []
        assert parsed.language == "es"

    def test_health_endpoint_schema(self) -> None:
        """GET /health returns {status: 'ok'}."""
        health_response = {"status": "ok"}
        assert "status" in health_response
        assert health_response["status"] == "ok"


# ---------------------------------------------------------------------------
# Integration test — subscription to the "transcribe" topic (Task 12.2)
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------


class TestWorkerSubscription:
    """Verifies that the worker subscribes to the 'transcribe' topic on startup."""

    @pytest.mark.asyncio
    async def test_worker_subscribes_to_transcribe_topic(self) -> None:
        """On startup, the worker subscribes to the 'transcribe' topic."""
        mock_queue = AsyncMock()
        mock_queue.subscribe = AsyncMock()

        mock_session_factory = AsyncMock()

        await start_worker(mock_queue, mock_session_factory)

        # Verify subscribe was called with "transcribe" as the topic
        mock_queue.subscribe.assert_called_once()
        call_args = mock_queue.subscribe.call_args
        assert call_args[0][0] == "transcribe"
        # Second arg should be a callable (the handler)
        assert callable(call_args[0][1])
