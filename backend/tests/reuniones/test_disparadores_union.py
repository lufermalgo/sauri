"""Unit tests de los disparadores de unión (solicitar_union, programar_union_por_calendario).

# Feature: meeting-capture-transcription
Task: 5.10 — Validates: Requirements 1.2, 1.3
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Reunion
from app.reuniones.service import programar_union_por_calendario, solicitar_union


def _crear_reunion_en_cola(reunion_id: str) -> Reunion:
    return Reunion(
        id=reunion_id,
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso="en_cola",
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_solicitar_union_manual_transiciona_y_encola(db_session: AsyncSession) -> None:
    """Req 1.2: la unión manual transiciona a 'uniendose' y encola un trabajo de unión."""
    reunion_id = str(uuid.uuid4())
    reunion = _crear_reunion_en_cola(reunion_id)
    db_session.add(reunion)
    await db_session.flush()

    cola = AsyncMock()
    resultado = await solicitar_union(db_session, reunion_id, cola)

    assert resultado.exitosa is True
    assert resultado.nuevo_estado == "uniendose"
    cola.publicar.assert_awaited_once_with(
        tema="union",
        mensaje={"reunion_id": reunion_id, "enlace_meet": reunion.enlace_meet},
    )


@pytest.mark.asyncio
async def test_solicitar_union_reunion_inexistente_no_publica(
    db_session: AsyncSession,
) -> None:
    """Si la Reunion no existe, no se publica ningún trabajo."""
    cola = AsyncMock()
    resultado = await solicitar_union(db_session, "no-existe", cola)

    assert resultado.exitosa is False
    cola.publicar.assert_not_awaited()


@pytest.mark.asyncio
async def test_programar_union_por_calendario_dispara_al_llegar_la_hora(
    db_session: AsyncSession,
) -> None:
    """Req 1.3: el disparo programado por calendario transiciona y encola igual que la unión manual."""
    reunion_id = str(uuid.uuid4())
    reunion = _crear_reunion_en_cola(reunion_id)
    reunion.origen = "invitacion_calendario"
    reunion.id_invitacion_calendario = "cal-evt-1"
    reunion.hora_inicio_programada = datetime.now(UTC)
    db_session.add(reunion)
    await db_session.flush()

    cola = AsyncMock()
    resultado = await programar_union_por_calendario(db_session, reunion_id, cola)

    assert resultado.exitosa is True
    assert resultado.nuevo_estado == "uniendose"
    cola.publicar.assert_awaited_once_with(
        tema="union",
        mensaje={"reunion_id": reunion_id, "enlace_meet": reunion.enlace_meet},
    )
