"""Property test de consistencia de consulta de estado (consultar_reunion).

# Feature: meeting-capture-transcription, Property 5: Consistencia de la consulta de estado
Task: 5.8
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Reunion
from app.reuniones.service import consultar_reunion
from app.reuniones.state_machine import CAUSAS_FALLO_VALIDAS, ESTADOS


def _crear_reunion(estado: str, causa_fallo: str | None) -> Reunion:
    return Reunion(
        id=str(uuid.uuid4()),
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso=estado,
        causa_fallo=causa_fallo,
        creada_por="test-user",
        creada_en=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 5: Consistencia de la consulta de estado
# Feature: meeting-capture-transcription, Property 5: Consistencia de la consulta de estado
# Validates: Requirements 4.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    estado=st.sampled_from(sorted(ESTADOS)),
    causa_fallo=st.sampled_from(sorted(CAUSAS_FALLO_VALIDAS)),
)
@pytest.mark.asyncio
async def test_property_5_causa_fallo_presente_si_y_solo_si_fallido(
    db_session: AsyncSession, estado: str, causa_fallo: str
) -> None:
    """causa_fallo aparece en el resultado si y solo si estado_proceso == 'fallido'."""
    reunion = _crear_reunion(estado, causa_fallo if estado == "fallido" else None)
    db_session.add(reunion)
    await db_session.flush()

    resultado = await consultar_reunion(db_session, reunion.id)

    assert resultado["estado_proceso"] == estado
    assert resultado["reunion_id"] == reunion.id

    if estado == "fallido":
        assert "causa_fallo" in resultado
        assert resultado["causa_fallo"] == causa_fallo
    else:
        assert "causa_fallo" not in resultado


@pytest.mark.asyncio
async def test_ejemplo_consultar_reunion_inexistente_lanza_error(
    db_session: AsyncSession,
) -> None:
    """Consultar una Reunion inexistente lanza ValueError."""
    with pytest.raises(ValueError):
        await consultar_reunion(db_session, "no-existe")
