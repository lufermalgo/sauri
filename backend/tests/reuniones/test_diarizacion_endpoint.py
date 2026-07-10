"""Contrato de GET /api/v1/reuniones/{id}/diarizacion (chrome-side-panel, Tarea 13.1).

Validates: Requirements 6.3, 14.1
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.auth.token import crear_token
from app.infra.models import (
    AsignacionDeHablante,
    Diarizacion,
    Hablante,
    Reunion,
    Transcripcion,
    TurnoDeHabla,
)

USUARIO_ID = "user-diar-test"


def _auth_header() -> dict[str, str]:
    token = crear_token(USUARIO_ID, "diar@sauri.local", "Diar Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _session_factory(api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_diarizacion_200_con_hablantes_y_asignaciones(api_client: AsyncClient, api_db_url: str):
    session_factory, engine = await _session_factory(api_db_url)
    reunion_id = str(uuid.uuid4())
    transcripcion_id = str(uuid.uuid4())
    diarizacion_id = str(uuid.uuid4())
    turno_id = str(uuid.uuid4())
    hablante_id = str(uuid.uuid4())
    ahora = datetime.now(timezone.utc)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                Reunion(
                    id=reunion_id,
                    enlace_meet="https://meet.google.com/abc-defg-hij",
                    origen="enlace",
                    id_invitacion_calendario=None,
                    hora_inicio_programada=None,
                    estado_proceso="completado",
                    causa_fallo=None,
                    creada_por=USUARIO_ID,
                    creada_en=ahora,
                )
            )
            session.add(
                Transcripcion(
                    id=transcripcion_id,
                    reunion_id=reunion_id,
                    idioma="es-CO",
                    proveedor="local",
                    soporta_turnos=True,
                    expira_en=None,
                    creada_en=ahora,
                )
            )
            session.add(
                TurnoDeHabla(
                    id=turno_id,
                    transcripcion_id=transcripcion_id,
                    texto="Hola",
                    inicio_ms=0,
                    fin_ms=1000,
                    orden=0,
                )
            )
            session.add(
                Diarizacion(
                    id=diarizacion_id,
                    reunion_id=reunion_id,
                    transcripcion_id=transcripcion_id,
                    proveedor="local",
                    num_hablantes=1,
                    estado_diarizacion="completada",
                    causa_fallo=None,
                    creada_en=ahora,
                    actualizada_en=ahora,
                )
            )
            session.add(
                Hablante(
                    id=hablante_id,
                    diarizacion_id=diarizacion_id,
                    etiqueta_cruda="SPEAKER_00",
                    etiqueta="Hablante 1",
                    orden=1,
                )
            )
            session.add(
                AsignacionDeHablante(
                    id=str(uuid.uuid4()),
                    diarizacion_id=diarizacion_id,
                    turno_id=turno_id,
                    hablante_id=hablante_id,
                )
            )
    await engine.dispose()

    resp = await api_client.get(
        f"/api/v1/reuniones/{reunion_id}/diarizacion", headers=_auth_header()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["diarizacion_id"] == diarizacion_id
    assert body["reunion_id"] == reunion_id
    assert body["estado_diarizacion"] == "completada"
    assert body["num_hablantes"] == 1
    assert len(body["hablantes"]) == 1
    assert body["hablantes"][0]["etiqueta"] == "Hablante 1"
    assert body["hablantes"][0]["orden"] == 1
    assert len(body["asignaciones"]) == 1
    assert body["asignaciones"][0]["turno_id"] == turno_id
    assert body["asignaciones"][0]["hablante_id"] == hablante_id


@pytest.mark.asyncio
async def test_diarizacion_404_reunion_inexistente(api_client: AsyncClient):
    resp = await api_client.get(
        f"/api/v1/reuniones/{uuid.uuid4()}/diarizacion", headers=_auth_header()
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diarizacion_404_sin_diarizacion(api_client: AsyncClient, api_db_url: str):
    session_factory, engine = await _session_factory(api_db_url)
    reunion_id = str(uuid.uuid4())
    ahora = datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Reunion(
                    id=reunion_id,
                    enlace_meet="https://meet.google.com/abc-defg-hij",
                    origen="enlace",
                    id_invitacion_calendario=None,
                    hora_inicio_programada=None,
                    estado_proceso="completado",
                    causa_fallo=None,
                    creada_por=USUARIO_ID,
                    creada_en=ahora,
                )
            )
    await engine.dispose()

    resp = await api_client.get(
        f"/api/v1/reuniones/{reunion_id}/diarizacion", headers=_auth_header()
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diarizacion_requiere_autenticacion(api_client: AsyncClient):
    resp = await api_client.get(f"/api/v1/reuniones/{uuid.uuid4()}/diarizacion")
    assert resp.status_code == 401
