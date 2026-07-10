"""Contrato aditivo: `id` del Turno en cada segmento de GET /transcripcion
(chrome-side-panel, Tarea 13.3). Validates: Requirements 8.1, 14.1, 14.2
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import crear_token
from app.infra.models import Reunion, Transcripcion, TurnoDeHabla

USUARIO_ID = "user-turno-test"


def _auth_header() -> dict[str, str]:
    token = crear_token(USUARIO_ID, "turno@sauri.local", "Turno Test", True)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_segmentos_incluyen_id_del_turno(api_client: AsyncClient, api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    reunion_id = str(uuid.uuid4())
    transcripcion_id = str(uuid.uuid4())
    turno_id = str(uuid.uuid4())
    ahora = datetime.now(UTC)

    async with session_factory() as session, session.begin():
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
                texto="Hola mundo",
                inicio_ms=0,
                fin_ms=1500,
                orden=0,
            )
        )
    await engine.dispose()

    resp = await api_client.get(
        f"/api/v1/reuniones/{reunion_id}/transcripcion", headers=_auth_header()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["segmentos"]) == 1
    segmento = body["segmentos"][0]
    assert segmento["id"] == turno_id
    # Campos existentes se preservan (cambio aditivo)
    assert segmento["texto"] == "Hola mundo"
    assert segmento["inicio_ms"] == 0
    assert segmento["fin_ms"] == 1500
    assert segmento["orden"] == 0
