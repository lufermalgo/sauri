"""Tests para el ProveedorNube (proveedor_nube.py).

# Feature: transcripcion-asr
Tasks: 5.2, 5.3, 5.4
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcripcion.motor_asr import OpcionesTranscripcion
from app.transcripcion.proveedor_nube import ErrorServicioExterno, ProveedorNube


# ---------------------------------------------------------------------------
# Property 3: Rechazo de endpoint no cifrado (Task 5.2)
# Feature: transcripcion-asr, Property 3: Rechazo de endpoint no cifrado
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------


@given(
    scheme=st.sampled_from(["http://", "ftp://", "ws://", ""]),
    host=st.from_regex(r"[a-z]{3,10}\.[a-z]{2,4}", fullmatch=True),
)
def test_property_3_rechazo_endpoint_no_cifrado(scheme: str, host: str):
    """Endpoint sin HTTPS → ValueError al construir ProveedorNube."""
    endpoint = scheme + host + "/transcribe"
    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": endpoint,
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="HTTPS"):
            ProveedorNube()


# ---------------------------------------------------------------------------
# Property 5: Validez de los segmentos del resultado (Task 5.3)
# Feature: transcripcion-asr, Property 5: Validez de los segmentos
# Validates: Requirements 4.5, 5.2, 5.3, 5.4
# ---------------------------------------------------------------------------

valid_segment_strategy = st.fixed_dictionaries(
    {
        "text": st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
        "start_ms": st.integers(min_value=0, max_value=10_000_000),
        "end_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(lambda s: s["end_ms"] >= s["start_ms"])

invalid_segment_strategy = st.one_of(
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
async def test_property_5_solo_segmentos_validos_en_resultado(
    valid_segs: list[dict], invalid_segs: list[dict]
):
    """Solo los segmentos con texto no vacío, inicio>=0, fin>=inicio se incluyen."""
    all_segments = valid_segs + invalid_segs
    response_data = {"segments": all_segments}

    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        proveedor = ProveedorNube()

    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    with patch("app.transcripcion.proveedor_nube.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.transcribir("audio/test.webm", opciones)

    # All returned segments must be valid
    for seg in resultado.segmentos:
        assert seg.texto.strip()
        assert seg.inicio_ms >= 0
        assert seg.fin_ms >= seg.inicio_ms

    # Count should match valid segments only
    assert len(resultado.segmentos) == len(valid_segs)


# ---------------------------------------------------------------------------
# Pruebas por ejemplo/integración del proveedor nube (Task 5.4)
# Validates: Requirements 4.1, 4.3, 4.4, 4.6
# ---------------------------------------------------------------------------


def test_ejemplo_api_key_ausente_lanza_valueerror():
    """Req 4.4: ASR_CLOUD_API_KEY ausente → ValueError."""
    env = {
        "ASR_CLOUD_API_KEY": "",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="ASR_CLOUD_API_KEY"):
            ProveedorNube()


@pytest.mark.asyncio
async def test_ejemplo_timeout_cloud_lanza_error_servicio():
    """Req 4.6: Timeout del servicio cloud → ErrorServicioExterno."""
    env = {
        "ASR_CLOUD_API_KEY": "valid-key",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        proveedor = ProveedorNube()

    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    with patch("app.transcripcion.proveedor_nube.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ErrorServicioExterno, match="timeout"):
            await proveedor.transcribir("audio/test.webm", opciones)


@pytest.mark.asyncio
async def test_ejemplo_integracion_https_y_auth_header():
    """Req 4.1, 4.3: Usa HTTPS y envía cabecera Authorization Bearer."""
    env = {
        "ASR_CLOUD_API_KEY": "sk-my-secret",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/v1/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        proveedor = ProveedorNube()

    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "segments": [{"text": "hola", "start_ms": 0, "end_ms": 1000}]
    }

    with patch("app.transcripcion.proveedor_nube.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resultado = await proveedor.transcribir("audio/test.webm", opciones)

        # Verify post was called with HTTPS endpoint and auth header
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/transcribe"
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-my-secret"

    assert len(resultado.segmentos) == 1
