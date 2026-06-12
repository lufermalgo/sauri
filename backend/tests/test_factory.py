"""Tests para la Fabrica_De_Motor (factory.py).

# Feature: transcripcion-asr
Tasks: 3.2, 3.3, 3.4
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcripcion.factory import crear_motor_asr
from app.transcripcion.proveedor_local import ProveedorLocal
from app.transcripcion.proveedor_nube import ProveedorNube


# ---------------------------------------------------------------------------
# Property 1: Selección del proveedor por configuración (Task 3.2)
# Feature: transcripcion-asr, Property 1: Selección del proveedor por configuración
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------


@given(
    padding=st.text(alphabet=" \t", min_size=0, max_size=5),
)
def test_property_1_local_con_variantes(padding: str):
    """ASR_PROVIDER='local' (con espacios/tabs) → ProveedorLocal."""
    provider_value = padding + "local" + padding
    env = {
        "ASR_PROVIDER": provider_value,
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorLocal)


@given(
    padding=st.text(alphabet=" \t", min_size=0, max_size=5),
)
def test_property_1_cloud_con_variantes(padding: str):
    """ASR_PROVIDER='cloud' (con capitalización y espacios) → ProveedorNube."""
    provider_value = padding + "cloud" + padding
    env = {
        "ASR_PROVIDER": provider_value,
        "ASR_CLOUD_API_KEY": "test-key-123",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorNube)


@given(
    value=st.sampled_from(["", "   ", "\t", "\t  "]),
)
def test_property_1_ausente_o_vacio_es_local(value: str):
    """ASR_PROVIDER vacío o solo espacios → ProveedorLocal (default)."""
    env = {
        "ASR_PROVIDER": value,
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorLocal)


def test_property_1_ausente_sin_variable():
    """ASR_PROVIDER no definido → ProveedorLocal (default)."""
    env = {"ASR_LOCAL_URL": "http://asr-engine:8001"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("ASR_PROVIDER", None)
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorLocal)


# ---------------------------------------------------------------------------
# Property 2: Valor de proveedor inválido señala error con el valor recibido (Task 3.3)
# Feature: transcripcion-asr, Property 2: Valor inválido señala error
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------


@given(
    value=st.text(
        alphabet=st.characters(
            blacklist_characters="\x00",
            blacklist_categories=("Cs",),
        ),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s.strip().lower() not in ("", "local", "cloud")),
)
def test_property_2_valor_invalido_incluye_valor_en_error(value: str):
    """Valor no reconocido → ValueError que incluye el valor recibido."""
    import re

    env = {"ASR_PROVIDER": value}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match=re.escape(value.strip())):
            crear_motor_asr()


# ---------------------------------------------------------------------------
# Pruebas por ejemplo de la fábrica (Task 3.4)
# Validates: Requirements 2.2, 2.3, 2.6
# ---------------------------------------------------------------------------


def test_ejemplo_local_con_url_valida():
    """Req 2.2: 'local' con URL válida → ProveedorLocal configurado."""
    env = {
        "ASR_PROVIDER": "local",
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorLocal)


def test_ejemplo_cloud_con_configuracion_valida():
    """Req 2.3: 'cloud' con API key y endpoint HTTPS → ProveedorNube."""
    env = {
        "ASR_PROVIDER": "cloud",
        "ASR_CLOUD_API_KEY": "sk-test-123",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/v1/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        motor = crear_motor_asr()
        assert isinstance(motor, ProveedorNube)


def test_ejemplo_local_sin_url_lanza_valueerror():
    """Req 2.6: proveedor local sin ASR_LOCAL_URL → ValueError."""
    env = {"ASR_PROVIDER": "local", "ASR_LOCAL_URL": ""}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="ASR_LOCAL_URL"):
            crear_motor_asr()


def test_ejemplo_local_url_solo_espacios_lanza_valueerror():
    """Req 2.6: proveedor local con ASR_LOCAL_URL solo espacios → ValueError."""
    env = {"ASR_PROVIDER": "local", "ASR_LOCAL_URL": "   "}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="ASR_LOCAL_URL"):
            crear_motor_asr()
