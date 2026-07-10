"""Property test de control de acceso y auditoría (autorizacion.py, audit.py).

# Feature: meeting-capture-transcription, Property 10: Control de acceso y auditoría
Task: 8.2 — Validates: Requirements 7.3, 7.4, 9.1, 9.2, 9.3
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.authorization import requerir_comercial, verificar_autorizacion
from app.auth.dependencies import obtener_usuario_actual
from app.auth.schemas import UsuarioAutenticado
from app.infra.models import RegistroDeAcceso


def _construir_app(session_factory: async_sessionmaker[AsyncSession], usuario: UsuarioAutenticado) -> FastAPI:
    app = FastAPI()

    async def get_session():
        async with session_factory() as session:
            yield session

    dependencia = requerir_comercial(get_session)

    @app.get("/recurso-protegido")
    async def endpoint(usuario_autorizado: UsuarioAutenticado = Depends(dependencia)):
        return {"id": usuario_autorizado.id}

    app.dependency_overrides[obtener_usuario_actual] = lambda: usuario
    return app


# ---------------------------------------------------------------------------
# Property 10: Control de acceso y auditoría
# Feature: meeting-capture-transcription, Property 10: Control de acceso y auditoría
# Validates: Requirements 7.3, 7.4, 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(es_comercial=st.booleans())
@pytest.mark.asyncio
async def test_property_10_acceso_concedido_si_y_solo_si_autorizado(
    session_factory: async_sessionmaker[AsyncSession], es_comercial: bool
) -> None:
    """Acceso concedido si y solo si el usuario autenticado es comercial (autorizado)."""
    usuario = UsuarioAutenticado(
        id="user-1", email="u@sauri.local", nombre="U", es_comercial=es_comercial
    )
    assert verificar_autorizacion(usuario, "recurso", "GET") is es_comercial

    app = _construir_app(session_factory, usuario)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/recurso-protegido")

    if es_comercial:
        assert response.status_code == 200
    else:
        assert response.status_code == 403


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(es_comercial=st.booleans())
@pytest.mark.asyncio
async def test_property_10_toda_denegacion_genera_exactamente_un_registro(
    session_factory: async_sessionmaker[AsyncSession], es_comercial: bool
) -> None:
    """Toda denegación de acceso genera exactamente una entrada de RegistroDeAcceso con resultado='denegado'."""
    usuario = UsuarioAutenticado(
        id=str(uuid.uuid4()), email="u2@sauri.local", nombre="U2", es_comercial=es_comercial
    )
    app = _construir_app(session_factory, usuario)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/recurso-protegido")

    async with session_factory() as session:
        result = await session.execute(
            select(RegistroDeAcceso).where(RegistroDeAcceso.usuario_id == usuario.id)
        )
        registros = result.scalars().all()

    if es_comercial:
        assert registros == []
    else:
        assert len(registros) == 1
        assert registros[0].resultado == "denegado"
