"""Tests para la lectura/validación de reintentos por tema en queue_rabbitmq.py.

# Feature: identificacion-hablantes
# Task: 12.1 — Escribir prueba de la lectura/validación de reintentos por tema (RED)
# Validates: Requirements 10.2

Verifica que `_leer_max_retries` generalizada honra `DIARIZATION_MAX_RETRIES`
para el tema "diarizar" (rango 0–10, default 3) sin romper la lectura de
`ASR_MAX_RETRIES` para "transcribir".
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.infra.queue_rabbitmq import _leer_max_retries


class TestLeerMaxRetriesDiarizar:
    """Pruebas de _leer_max_retries para el tema 'diarizar' con DIARIZATION_MAX_RETRIES."""

    def test_valor_explicito_5(self):
        """DIARIZATION_MAX_RETRIES=5 → para tema 'diarizar', max retries = 5."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "5"}, clear=False):
            assert _leer_max_retries("diarizar") == 5

    def test_default_cuando_ausente(self):
        """DIARIZATION_MAX_RETRIES ausente → default 3 para 'diarizar'."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DIARIZATION_MAX_RETRIES", None)
            assert _leer_max_retries("diarizar") == 3

    def test_valor_0_valido(self):
        """DIARIZATION_MAX_RETRIES=0 → 0 reintentos (válido)."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "0"}, clear=False):
            assert _leer_max_retries("diarizar") == 0

    def test_valor_10_valido(self):
        """DIARIZATION_MAX_RETRIES=10 → 10 reintentos (edge válido)."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "10"}, clear=False):
            assert _leer_max_retries("diarizar") == 10

    def test_valor_11_fuera_de_rango(self):
        """DIARIZATION_MAX_RETRIES=11 → acotado a default 3."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "11"}, clear=False):
            assert _leer_max_retries("diarizar") == 3

    def test_valor_negativo_fuera_de_rango(self):
        """DIARIZATION_MAX_RETRIES=-1 → acotado a default 3."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "-1"}, clear=False):
            assert _leer_max_retries("diarizar") == 3


class TestLeerMaxRetriesTranscribirNoRoto:
    """Verifica que la generalización no rompe el comportamiento de 'transcribir'."""

    def test_asr_max_retries_sigue_funcionando(self):
        """ASR_MAX_RETRIES=2 con tema 'transcribir' → sigue leyendo 2."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "2"}, clear=False):
            assert _leer_max_retries("transcribir") == 2
