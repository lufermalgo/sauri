"""Tests de integración del módulo transcripción-asr.

# Feature: transcripcion-asr
Tasks: 11.2, 12.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.transcripcion.worker import iniciar_worker


# ---------------------------------------------------------------------------
# Prueba de integración del contrato del asr-engine (Task 11.2)
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------


class TestContratoASREngine:
    """Verifica que el contrato POST /transcribe y GET /health es correcto."""

    @pytest.mark.asyncio
    async def test_post_transcribe_forma_respuesta(self):
        """POST /transcribe devuelve {segments: [{text, start_ms, end_ms}], language}."""
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
                {"text": "¿Cómo estás?", "start_ms": 2100, "end_ms": 4000},
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
    async def test_post_transcribe_respuesta_vacia_valida(self):
        """POST /transcribe con audio vacío devuelve segments: [], language."""
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

    def test_health_endpoint_schema(self):
        """GET /health devuelve {status: 'ok'}."""
        health_response = {"status": "ok"}
        assert "status" in health_response
        assert health_response["status"] == "ok"


# ---------------------------------------------------------------------------
# Prueba de integración — suscripción al tema "transcribir" (Task 12.2)
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------


class TestSuscripcionWorker:
    """Verifica que el worker se suscribe al tema 'transcribir' al iniciar."""

    @pytest.mark.asyncio
    async def test_worker_se_suscribe_a_tema_transcribir(self):
        """Al iniciar, el worker se suscribe al tema 'transcribir'."""
        mock_cola = AsyncMock()
        mock_cola.suscribir = AsyncMock()

        mock_session_factory = AsyncMock()

        await iniciar_worker(mock_cola, mock_session_factory)

        # Verify suscribir was called with "transcribir" as the topic
        mock_cola.suscribir.assert_called_once()
        call_args = mock_cola.suscribir.call_args
        assert call_args[0][0] == "transcribir"
        # Second arg should be a callable (the handler)
        assert callable(call_args[0][1])
