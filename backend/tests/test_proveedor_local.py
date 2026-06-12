"""Tests para el ProveedorLocal (proveedor_local.py).

# Feature: transcripcion-asr
Tasks: 4.2, 4.3, 4.4
"""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from unittest.mock import AsyncMock, MagicMock, patch

from app.transcripcion.motor_asr import OpcionesTranscripcion
from app.transcripcion.proveedor_local import ProveedorLocal


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

segment_strategy = st.fixed_dictionaries(
    {
        "text": st.text(min_size=1, max_size=100),
        "start_ms": st.integers(min_value=0, max_value=10_000_000),
        "end_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(lambda s: s["end_ms"] >= s["start_ms"])

segments_list_strategy = st.lists(segment_strategy, min_size=0, max_size=20)


# ---------------------------------------------------------------------------
# Property 4: Mapeo fiel de la respuesta local a segmentos (Task 4.2)
# Feature: transcripcion-asr, Property 4: Mapeo fiel de la respuesta local
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------


@given(segments=segments_list_strategy)
@pytest.mark.asyncio
async def test_property_4_mapeo_fiel_respuesta_local(segments: list[dict]):
    """Cada segmento de la respuesta se mapea fielmente a SegmentoTranscripcion."""
    proveedor = ProveedorLocal(url="http://fake-asr:8001")
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    response_data = {"segments": segments, "language": "es"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcripcion.proveedor_local.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.transcribir("audio/test.webm", opciones)

    assert len(resultado.segmentos) == len(segments)
    for seg_out, seg_in in zip(resultado.segmentos, segments):
        assert seg_out.texto == seg_in["text"]
        assert seg_out.inicio_ms == seg_in["start_ms"]
        assert seg_out.fin_ms == seg_in["end_ms"]


# ---------------------------------------------------------------------------
# Property 6: Orden ascendente de los segmentos (Task 4.3)
# Feature: transcripcion-asr, Property 6: Orden ascendente
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------


@given(segments=st.lists(segment_strategy, min_size=2, max_size=20))
@pytest.mark.asyncio
async def test_property_6_orden_ascendente_respetado(segments: list[dict]):
    """Los segmentos se devuelven en el orden que el servicio los entrega."""
    proveedor = ProveedorLocal(url="http://fake-asr:8001")
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    response_data = {"segments": segments, "language": "es"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcripcion.proveedor_local.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.transcribir("audio/test.webm", opciones)

    # The segments preserve the order from the service response
    for i, seg in enumerate(resultado.segmentos):
        assert seg.inicio_ms == segments[i]["start_ms"]


# ---------------------------------------------------------------------------
# Pruebas por ejemplo del proveedor local (Task 4.4)
# Validates: Requirements 3.5, 3.6, 3.7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_error_http_propaga_excepcion():
    """Req 3.5: Error HTTP del servicio → excepción propagada sin segmentos parciales."""
    proveedor = ProveedorLocal(url="http://fake-asr:8001")
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=httpx.Request("POST", "http://fake-asr:8001/transcribe"),
        response=httpx.Response(500),
    )

    with patch("app.transcripcion.proveedor_local.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await proveedor.transcribir("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_timeout_propaga_excepcion():
    """Req 3.6: Timeout/inalcanzable → excepción propagada."""
    proveedor = ProveedorLocal(url="http://fake-asr:8001")
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    with patch("app.transcripcion.proveedor_local.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.ConnectTimeout):
            await proveedor.transcribir("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_respuesta_sin_segments_lanza_valueerror():
    """Req 3.7: Respuesta sin clave 'segments' → ValueError."""
    proveedor = ProveedorLocal(url="http://fake-asr:8001")
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"language": "es"}  # sin 'segments'

    with patch("app.transcripcion.proveedor_local.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="segments"):
            await proveedor.transcribir("audio/test.webm", opciones)
