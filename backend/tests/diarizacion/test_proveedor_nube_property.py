# Feature: identificacion-hablantes, Property 3: Rechazo de endpoint no cifrado en el Proveedor_Nube
"""Prueba de propiedad: el Proveedor_Nube rechaza endpoints sin HTTPS.

**Validates: Requirements 4.2**

Para cualquier DIARIZATION_CLOUD_ENDPOINT cuyo esquema no sea https,
la inicialización del ProveedorNube falla con ValueError indicando
el esquema no soportado, sin transmitir audio.
"""

from __future__ import annotations

import os
import string
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Estrategias de generación
# ---------------------------------------------------------------------------

# Esquemas distintos de "https" con variantes conocidas y generadas
_scheme_known = st.sampled_from(["http://", "ftp://", "ws://", "wss://", "file://", ""])
_scheme_random = st.text(
    alphabet=string.ascii_lowercase + string.digits + "+-.",
    min_size=1,
    max_size=10,
).filter(lambda s: s != "https").map(lambda s: f"{s}://")

_non_https_scheme = st.one_of(_scheme_known, _scheme_random)

_host = st.from_regex(r"[a-z]{3,10}\.[a-z]{2,5}", fullmatch=True)

# URLs con esquema no-https
_non_https_endpoint = st.builds(
    lambda scheme, host: f"{scheme}{host}/diarize",
    _non_https_scheme,
    _host,
)

# Cadenas sin esquema (bare strings)
_bare_endpoint = st.text(
    alphabet=string.ascii_letters + string.digits + ".-_/",
    min_size=1,
    max_size=40,
).filter(lambda s: not s.startswith("https://"))

# Estrategia combinada de endpoints no-HTTPS
_endpoint_no_cifrado = st.one_of(_non_https_endpoint, _bare_endpoint)

# API key válida (no vacía, requerida para que el init no falle antes por la key)
_valid_api_key = st.text(
    alphabet=string.ascii_letters + string.digits + "-_",
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Prueba de propiedad
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(endpoint=_endpoint_no_cifrado, api_key=_valid_api_key)
def test_property_3_rechazo_endpoint_no_cifrado(endpoint: str, api_key: str) -> None:
    """Property 3: ProveedorNube rechaza endpoints sin HTTPS.

    Validates: Requirements 4.2

    Para cualquier DIARIZATION_CLOUD_ENDPOINT cuyo esquema no sea https,
    la inicialización del ProveedorNube falla con ValueError indicando
    el esquema no soportado, sin transmitir audio.
    """
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": endpoint,
        "DIARIZATION_CLOUD_API_KEY": api_key,
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ProveedorNube

        with pytest.raises(ValueError) as exc_info:
            ProveedorNube()

        # El mensaje debe indicar el esquema no soportado
        mensaje = str(exc_info.value).lower()
        assert "https" in mensaje or "esquema" in mensaje or "cifrado" in mensaje, (
            f"El ValueError no indica el esquema no soportado: {exc_info.value!r}"
        )


# Feature: identificacion-hablantes, Property 5: Validez de los Segmentos_De_Hablante del resultado
# ---------------------------------------------------------------------------
# Prueba de propiedad 5: Validez de los Segmentos_De_Hablante del resultado
#
# **Validates: Requirements 4.5, 5.2, 5.3, 5.4**
#
# Para cualquier ResultadoDiarizacion producido por el ProveedorNube sobre una
# GrabacionDeAudio de DuracionDeGrabacion D, todo SegmentoDeHablante cumple:
# inicio_ms y fin_ms son enteros, inicio_ms >= 0, fin_ms >= inicio_ms,
# fin_ms <= D, y etiqueta_cruda no vacía.
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Estrategias de generación para Property 5
# ---------------------------------------------------------------------------

# Duración total de grabación: entre 1000 ms y 10_000_000 ms
_duracion_ms_strategy = st.integers(min_value=1000, max_value=10_000_000)

# Etiqueta cruda no vacía
_etiqueta_cruda_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + "_",
    min_size=1,
    max_size=30,
)


@st.composite
def _segmento_valido_para_duracion(draw, duracion_ms: int):
    """Genera un segmento válido respetando las restricciones de duracion_ms."""
    speaker = draw(_etiqueta_cruda_strategy)
    start_ms = draw(st.integers(min_value=0, max_value=max(0, duracion_ms - 1)))
    end_ms = draw(st.integers(min_value=start_ms, max_value=duracion_ms))
    return {"speaker": speaker, "start_ms": start_ms, "end_ms": end_ms}


@st.composite
def _respuesta_nube_con_segmentos_validos(draw):
    """Genera una duracion_ms y segmentos válidos del servicio externo."""
    duracion = draw(_duracion_ms_strategy)
    num_segmentos = draw(st.integers(min_value=1, max_value=20))
    segmentos = [draw(_segmento_valido_para_duracion(duracion)) for _ in range(num_segmentos)]
    return duracion, segmentos


# ---------------------------------------------------------------------------
# Prueba de propiedad 5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=_respuesta_nube_con_segmentos_validos())
async def test_property_5_validez_segmentos_de_hablante(data) -> None:
    """Property 5: Validez de los Segmentos_De_Hablante del resultado.

    Validates: Requirements 4.5, 5.2, 5.3, 5.4

    Para cualquier respuesta válida del servicio externo con segmentos y una
    duracion_ms para la grabación, el ProveedorNube produce SegmentoDeHablante
    donde:
    - inicio_ms y fin_ms son enteros
    - inicio_ms >= 0
    - fin_ms >= inicio_ms
    - fin_ms <= duracion_ms
    - etiqueta_cruda es una cadena no vacía
    """
    duracion, segmentos_raw = data

    # Construir respuesta JSON simulada del servicio externo
    respuesta_json = {
        "segments": segmentos_raw,
        "num_speakers": len(set(s["speaker"] for s in segmentos_raw)),
    }

    # Mock de la respuesta HTTP
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = respuesta_json

    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }

    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ProveedorNube
        from app.diarizacion.motor_diarizacion import OpcionesDiarizacion

        proveedor = ProveedorNube()

        # Parchear httpx.AsyncClient para devolver la respuesta simulada
        with patch(
            "app.diarizacion.proveedor_nube.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            opciones = OpcionesDiarizacion(duracion_ms=duracion)
            resultado = await proveedor.diarizar("audio/test.wav", opciones)

    # Verificar la propiedad para cada segmento del resultado
    assert len(resultado.segmentos) > 0, "Debe haber al menos un segmento"

    for seg in resultado.segmentos:
        # inicio_ms es entero
        assert isinstance(seg.inicio_ms, int), (
            f"inicio_ms debe ser int, got {type(seg.inicio_ms)}"
        )
        # fin_ms es entero
        assert isinstance(seg.fin_ms, int), (
            f"fin_ms debe ser int, got {type(seg.fin_ms)}"
        )
        # inicio_ms >= 0
        assert seg.inicio_ms >= 0, (
            f"inicio_ms debe ser >= 0, got {seg.inicio_ms}"
        )
        # fin_ms >= inicio_ms
        assert seg.fin_ms >= seg.inicio_ms, (
            f"fin_ms ({seg.fin_ms}) debe ser >= inicio_ms ({seg.inicio_ms})"
        )
        # fin_ms <= duracion_ms
        assert seg.fin_ms <= duracion, (
            f"fin_ms ({seg.fin_ms}) debe ser <= duracion_ms ({duracion})"
        )
        # etiqueta_cruda es cadena no vacía
        assert isinstance(seg.etiqueta_cruda, str), (
            f"etiqueta_cruda debe ser str, got {type(seg.etiqueta_cruda)}"
        )
        assert len(seg.etiqueta_cruda) > 0, (
            "etiqueta_cruda no debe ser vacía"
        )


# ---------------------------------------------------------------------------
# Pruebas por ejemplo del Proveedor_Nube de diarización (Task 6.3)
# Validates: Requirements 4.4, 4.6
# ---------------------------------------------------------------------------

import httpx


def test_ejemplo_api_key_ausente_lanza_valueerror():
    """Req 4.4: DIARIZATION_CLOUD_API_KEY ausente → ValueError."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_CLOUD_API_KEY", None)
        from app.diarizacion.proveedor_nube import ProveedorNube

        with pytest.raises(ValueError, match="DIARIZATION_CLOUD_API_KEY"):
            ProveedorNube()


def test_ejemplo_api_key_vacia_lanza_valueerror():
    """Req 4.4: DIARIZATION_CLOUD_API_KEY vacía → ValueError."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "   ",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ProveedorNube

        with pytest.raises(ValueError, match="DIARIZATION_CLOUD_API_KEY"):
            ProveedorNube()


@pytest.mark.asyncio
async def test_ejemplo_timeout_120s_lanza_error_servicio_externo():
    """Req 4.6: Timeout de 120s → ErrorServicioExterno, conservando el audio."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ErrorServicioExterno, ProveedorNube
        from app.diarizacion.motor_diarizacion import OpcionesDiarizacion

        proveedor = ProveedorNube()

        with patch(
            "app.diarizacion.proveedor_nube.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ErrorServicioExterno, match="120"):
                await proveedor.diarizar("audio/test.wav", OpcionesDiarizacion())


@pytest.mark.asyncio
async def test_ejemplo_error_http_lanza_error_servicio_externo():
    """Req 4.6: Error HTTP del servicio externo → ErrorServicioExterno."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ErrorServicioExterno, ProveedorNube
        from app.diarizacion.motor_diarizacion import OpcionesDiarizacion

        proveedor = ProveedorNube()

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable",
            request=httpx.Request("POST", "https://api.example.com/diarize"),
            response=httpx.Response(503),
        )

        with patch(
            "app.diarizacion.proveedor_nube.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ErrorServicioExterno, match="503"):
                await proveedor.diarizar("audio/test.wav", OpcionesDiarizacion())


@pytest.mark.asyncio
async def test_ejemplo_respuesta_sin_segmentos_validos_retorna_vacio():
    """Req 4.6: Respuesta sin segmentos válidos → ResultadoDiarizacion con cero segmentos."""
    env = {
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.diarizacion.proveedor_nube import ProveedorNube
        from app.diarizacion.motor_diarizacion import OpcionesDiarizacion

        proveedor = ProveedorNube()

        # Respuesta con segmentos inválidos (inicio_ms > fin_ms)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "segments": [{"speaker": "", "start_ms": 100, "end_ms": 50}],
            "num_speakers": 0,
        }

        with patch(
            "app.diarizacion.proveedor_nube.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            resultado = await proveedor.diarizar("audio/test.wav", OpcionesDiarizacion())

    assert resultado.segmentos == []
    assert resultado.num_hablantes == 0
