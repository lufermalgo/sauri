"""Tests de propiedad para la Fabrica_De_Diarizacion (factory.py).

# Feature: identificacion-hablantes, Property 1: Selección del proveedor por configuración
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarizacion.factory import crear_motor_diarizacion
from app.diarizacion.proveedor_local import ProveedorLocal
from app.diarizacion.proveedor_nube import ProveedorNube


# ---------------------------------------------------------------------------
# Property 1: Selección del proveedor por configuración
# Feature: identificacion-hablantes, Property 1: Selección del proveedor por configuración
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------

# Strategy: generate "local" with arbitrary capitalization and padding
_local_capitalization = st.sampled_from(["local", "Local", "LOCAL", "lOcAl", "LocAL"])
_cloud_capitalization = st.sampled_from(["cloud", "Cloud", "CLOUD", "cLoUd", "ClOUD"])
_padding = st.text(alphabet=" \t", min_size=0, max_size=5)


@settings(max_examples=100)
@given(
    word=_local_capitalization,
    padding_left=_padding,
    padding_right=_padding,
)
def test_property_1_local_con_capitalizacion_y_espacios(
    word: str, padding_left: str, padding_right: str
):
    """DIARIZATION_PROVIDER='local' (capitalización/espacios arbitrarios) → ProveedorLocal."""
    provider_value = padding_left + word + padding_right
    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorLocal)


@settings(max_examples=100)
@given(
    word=_cloud_capitalization,
    padding_left=_padding,
    padding_right=_padding,
)
def test_property_1_cloud_con_capitalizacion_y_espacios(
    word: str, padding_left: str, padding_right: str
):
    """DIARIZATION_PROVIDER='cloud' (capitalización/espacios arbitrarios) → ProveedorNube."""
    provider_value = padding_left + word + padding_right
    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_CLOUD_ENDPOINT": "https://example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorNube)


@settings(max_examples=100)
@given(
    value=st.sampled_from(["", "   ", "\t", "\t  "]),
)
def test_property_1_vacio_es_local(value: str):
    """DIARIZATION_PROVIDER vacío o solo espacios → ProveedorLocal (default)."""
    env = {
        "DIARIZATION_PROVIDER": value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorLocal)


def test_property_1_ausente_sin_variable():
    """DIARIZATION_PROVIDER no definido → ProveedorLocal (default)."""
    env = {"DIARIZATION_LOCAL_URL": "http://diar-engine:8000"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_PROVIDER", None)
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorLocal)


# ---------------------------------------------------------------------------
# Property 2: Valor de proveedor inválido señala error con el valor recibido
# Feature: identificacion-hablantes, Property 2: Valor de proveedor inválido señala error con el valor recibido
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------

# Strategy: generate DIARIZATION_PROVIDER values that, when normalized
# (strip + lowercase), are NOT "local", "cloud", or empty/whitespace-only.
_invalid_provider = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00",
        blacklist_categories=("Cs",),  # Excluir surrogates (no válidos en env vars)
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip().lower() not in ("local", "cloud", ""))


@settings(max_examples=100)
@given(provider_value=_invalid_provider)
def test_property_2_valor_invalido_senala_error(provider_value: str):
    """Un DIARIZATION_PROVIDER inválido (normalizado ≠ local/cloud/vacío) lanza ValueError con el valor recibido."""
    import re

    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match=re.escape(provider_value.strip())):
            crear_motor_diarizacion()

# ---------------------------------------------------------------------------
# Pruebas por ejemplo de la Fabrica_De_Diarizacion (Task 4.3)
# Validates: Requirements 2.2, 2.3, 2.6
# ---------------------------------------------------------------------------


def test_ejemplo_local_con_url_definida():
    """Req 2.2: DIARIZATION_PROVIDER='local' con DIARIZATION_LOCAL_URL definida → ProveedorLocal."""
    env = {
        "DIARIZATION_PROVIDER": "local",
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8002",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorLocal)


def test_ejemplo_cloud_con_endpoint_y_key():
    """Req 2.3: DIARIZATION_PROVIDER='cloud' con endpoint HTTPS y API key → ProveedorNube."""
    env = {
        "DIARIZATION_PROVIDER": "cloud",
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.diarization.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "sk-test-key-12345",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_diarizacion()
        assert isinstance(motor, ProveedorNube)


def test_ejemplo_local_url_ausente_lanza_valueerror():
    """Req 2.6: Proveedor local seleccionado pero DIARIZATION_LOCAL_URL ausente → ValueError."""
    env = {"DIARIZATION_PROVIDER": "local"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_LOCAL_URL", None)
        with pytest.raises(ValueError, match="DIARIZATION_LOCAL_URL"):
            crear_motor_diarizacion()


def test_ejemplo_local_url_vacia_lanza_valueerror():
    """Req 2.6: Proveedor local seleccionado pero DIARIZATION_LOCAL_URL vacía → ValueError."""
    env = {
        "DIARIZATION_PROVIDER": "local",
        "DIARIZATION_LOCAL_URL": "   ",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="DIARIZATION_LOCAL_URL"):
            crear_motor_diarizacion()
