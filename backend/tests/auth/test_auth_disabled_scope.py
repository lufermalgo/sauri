"""Restricción de AUTH_DISABLED al entorno de test (chrome-side-panel, Tarea 13.11).

Validates: Requirements 13.1, 13.4
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.dependencies import obtener_usuario_actual


@pytest.mark.asyncio
async def test_bypass_activo_en_entorno_test(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("APP_ENV", "test")

    usuario = await obtener_usuario_actual(credentials=None)
    assert usuario.id == "dev-user-00000000"


@pytest.mark.asyncio
async def test_bypass_inactivo_fuera_de_entorno_test(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(HTTPException):
        await obtener_usuario_actual(credentials=None)


@pytest.mark.asyncio
async def test_bypass_inactivo_sin_app_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(HTTPException):
        await obtener_usuario_actual(credentials=None)
