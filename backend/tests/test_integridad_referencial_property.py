"""Property test de integridad referencial 1:1 (Grabacion_De_Sesion / Transcripcion ↔ Reunion).

# Feature: meeting-capture-transcription, Property 6: Integridad referencial 1:1
Task: 4.2 — Validates: Requirements 2.2, 2.3, 3.3
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import GrabacionDeSesion, Reunion, Transcripcion


def _crear_reunion(reunion_id: str) -> Reunion:
    return Reunion(
        id=reunion_id,
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso="grabando",
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(UTC),
    )


def _crear_grabacion(reunion_id: str, clave: str) -> GrabacionDeSesion:
    return GrabacionDeSesion(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        clave_idempotencia=clave,
        origen_captura="extension_chrome",
        audio_ref=f"audio/{uuid.uuid4()}.webm",
        video_ref=None,
        duracion_segundos=60,
        interrumpida=False,
        finalizada_en=datetime.now(UTC),
    )


def _crear_transcripcion(reunion_id: str) -> Transcripcion:
    return Transcripcion(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        idioma="es-CO",
        proveedor="local",
        soporta_turnos=True,
        expira_en=None,
        creada_en=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 6: Integridad referencial 1:1
# Feature: meeting-capture-transcription, Property 6: Integridad referencial 1:1
# Validates: Requirements 2.2, 2.3, 3.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_intentos=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_6_una_reunion_a_lo_sumo_una_grabacion(
    db_session: AsyncSession, n_intentos: int
) -> None:
    """Ninguna Reunion tiene más de una Grabacion_De_Sesion: solo el primer insert por reunion_id triunfa."""
    reunion_id = str(uuid.uuid4())
    db_session.add(_crear_reunion(reunion_id))
    await db_session.flush()

    exitosos = 0
    for i in range(n_intentos):
        grabacion = _crear_grabacion(reunion_id, clave=f"clave-{uuid.uuid4()}-{i}")
        try:
            async with db_session.begin_nested():
                db_session.add(grabacion)
                await db_session.flush()
            exitosos += 1
        except IntegrityError:
            pass

    assert exitosos == 1


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_intentos=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_6_una_reunion_a_lo_sumo_una_transcripcion(
    db_session: AsyncSession, n_intentos: int
) -> None:
    """Cada Transcripcion referencia su Reunion y ninguna Reunion tiene más de una Transcripcion."""
    reunion_id = str(uuid.uuid4())
    db_session.add(_crear_reunion(reunion_id))
    await db_session.flush()

    exitosos = 0
    for _ in range(n_intentos):
        transcripcion = _crear_transcripcion(reunion_id)
        try:
            async with db_session.begin_nested():
                db_session.add(transcripcion)
                await db_session.flush()
            exitosos += 1
        except IntegrityError:
            pass

    assert exitosos == 1


@pytest.mark.asyncio
async def test_ejemplo_grabacion_referencia_su_reunion(db_session: AsyncSession) -> None:
    """La Grabacion_De_Sesion persistida referencia exactamente la Reunion con la que se creó."""
    reunion_id = str(uuid.uuid4())
    db_session.add(_crear_reunion(reunion_id))
    grabacion = _crear_grabacion(reunion_id, clave=str(uuid.uuid4()))
    db_session.add(grabacion)
    await db_session.flush()

    assert grabacion.reunion_id == reunion_id
