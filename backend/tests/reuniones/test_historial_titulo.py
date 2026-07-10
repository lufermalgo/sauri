"""Contrato aditivo: campo `titulo` (nullable) en GET /api/v1/reuniones/
(chrome-side-panel, Tarea 13.5). Validates: Requirements 4.3, 4.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import crear_token
from app.infra.models import Reunion

USUARIO_ID = "user-titulo-test"


def _auth_header() -> dict[str, str]:
    token = crear_token(USUARIO_ID, "titulo@sauri.local", "Titulo Test", True)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_historial_incluye_titulo_nulo(api_client: AsyncClient, api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

    resp = await api_client.get("/api/v1/reuniones/", headers=_auth_header())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert "titulo" in item
    assert item["titulo"] is None
    # Campos existentes se preservan (cambio aditivo)
    assert item["reunion_id"] == reunion_id
    assert item["estado_proceso"] == "completado"
