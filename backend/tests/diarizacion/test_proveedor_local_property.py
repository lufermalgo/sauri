"""Tests de propiedad para el ProveedorLocal de diarización.

# Feature: identificacion-hablantes, Property 4: Mapeo fiel de la respuesta local a Segmentos_De_Hablante
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from unittest.mock import AsyncMock, MagicMock, patch

from app.diarizacion.proveedor_local import ProveedorLocal
from app.diarizacion.motor_diarizacion import OpcionesDiarizacion


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

segment_strategy = st.fixed_dictionaries(
    {
        "speaker": st.text(min_size=1, max_size=50),
        "start_ms": st.integers(min_value=0, max_value=10_000_000),
        "end_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(lambda s: s["end_ms"] >= s["start_ms"])

segments_list_strategy = st.lists(segment_strategy, min_size=0, max_size=20)


# ---------------------------------------------------------------------------
# Property 4: Mapeo fiel de la respuesta local a Segmentos_De_Hablante
# Feature: identificacion-hablantes, Property 4: Mapeo fiel de la respuesta local a Segmentos_De_Hablante
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segments=segments_list_strategy)
@pytest.mark.asyncio
async def test_property_4_mapeo_fiel_respuesta_local_diarizacion(
    segments: list[dict],
):
    """Para cualquier respuesta válida con N elementos {speaker, start_ms, end_ms},
    el ProveedorLocal produce exactamente N SegmentoDeHablante preservando
    etiqueta_cruda=speaker, inicio_ms=start_ms, fin_ms=end_ms en el mismo orden.

    **Validates: Requirements 3.4**
    """
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    response_data = {
        "segments": segments,
        "num_speakers": len({s["speaker"] for s in segments}),
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.diarizar("audio/test.webm", opciones)

    # Exactamente N segmentos producidos
    assert len(resultado.segmentos) == len(segments)

    # Preservación fiel de cada campo (el ResultadoDiarizacion ordena por inicio_ms
    # según Property 6 / Req. 5.1, así que comparamos tras ordenar la entrada)
    expected_tuples = sorted(
        [(s["speaker"], s["start_ms"], s["end_ms"]) for s in segments],
        key=lambda t: t[1],
    )
    actual_tuples = [
        (s.etiqueta_cruda, s.inicio_ms, s.fin_ms) for s in resultado.segmentos
    ]
    assert actual_tuples == expected_tuples


# ---------------------------------------------------------------------------
# Pruebas por ejemplo del ProveedorLocal de diarización (Task 5.2)
# Validates: Requirements 3.5, 3.6, 3.7
# ---------------------------------------------------------------------------

import httpx


@pytest.mark.asyncio
async def test_ejemplo_error_http_500_no_produce_segmentos_parciales():
    """Req 3.5: Error HTTP (status 500) → el proveedor señala fallo sin segmentos parciales."""
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=httpx.Request("POST", "http://fake-diar-engine:8002/diarize"),
        response=httpx.Response(500),
    )

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await proveedor.diarizar("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_timeout_senala_fallo():
    """Req 3.6: Timeout (httpx.TimeoutException) → el proveedor señala fallo."""
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.TimeoutException):
            await proveedor.diarizar("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_connect_error_senala_fallo():
    """Req 3.6: ConnectError (httpx.ConnectError) → el proveedor señala fallo."""
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.ConnectError):
            await proveedor.diarizar("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_respuesta_sin_segments_lanza_valueerror():
    """Req 3.7: Respuesta sin clave 'segments' → ValueError (estructura inválida)."""
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    # Respuesta sin la clave "segments" — estructura inválida
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"num_speakers": 2}

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="segments"):
            await proveedor.diarizar("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_segments_vacia_es_resultado_valido():
    """Req 3.7: `segments: []` (lista vacía) es un resultado válido — no lanza error.
    Esto distingue la ausencia de la clave (ValueError) del resultado sin hablantes.
    """
    proveedor = ProveedorLocal(url="http://fake-diar-engine:8002")
    opciones = OpcionesDiarizacion()

    # segments: [] es una respuesta válida (sin hablantes detectados)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"segments": [], "num_speakers": 0}

    with patch(
        "app.diarizacion.proveedor_local.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.diarizar("audio/test.webm", opciones)

    # No lanza excepción y produce cero segmentos
    assert resultado.segmentos == []
