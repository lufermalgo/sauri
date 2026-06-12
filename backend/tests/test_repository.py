"""Tests para el Repositorio_De_Transcripcion (repository.py).

# Feature: transcripcion-asr
Tasks: 7.3, 7.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import given, HealthCheck, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Reunion, Transcripcion, TurnoDeHabla
from app.transcripcion.repository import TranscripcionRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_reunion(reunion_id: str) -> Reunion:
    return Reunion(
        id=reunion_id,
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso="transcribiendo",
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(timezone.utc),
    )


def _crear_transcripcion(reunion_id: str) -> tuple[Transcripcion, str]:
    t_id = str(uuid.uuid4())
    return Transcripcion(
        id=t_id,
        reunion_id=reunion_id,
        idioma="es-CO",
        proveedor="local",
        soporta_turnos=True,
        expira_en=None,
        creada_en=datetime.now(timezone.utc),
    ), t_id


def _crear_turnos(transcripcion_id: str, n: int) -> list[TurnoDeHabla]:
    turnos = []
    for i in range(n):
        turnos.append(
            TurnoDeHabla(
                id=str(uuid.uuid4()),
                transcripcion_id=transcripcion_id,
                texto=f"Texto segmento {i+1}",
                inicio_ms=i * 1000,
                fin_ms=(i + 1) * 1000,
                orden=i + 1,
            )
        )
    return turnos


# ---------------------------------------------------------------------------
# Property 13: Round-trip de persistencia y recuperación (Task 7.3)
# Feature: transcripcion-asr, Property 13: Round-trip persistencia
# Validates: Requirements 7.7
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_turnos=st.integers(min_value=1, max_value=10))
@pytest.mark.asyncio
async def test_property_13_roundtrip_persistencia(
    session_factory: async_sessionmaker, num_turnos: int
):
    """Crear y recuperar una Transcripcion con N turnos preserva todos los datos."""
    reunion_id = str(uuid.uuid4())
    repo = TranscripcionRepository(session_factory)

    # Persist
    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion(reunion_id)
            session.add(reunion)

            transcripcion, t_id = _crear_transcripcion(reunion_id)
            turnos = _crear_turnos(t_id, num_turnos)
            await repo.crear(session, transcripcion, turnos)

    # Retrieve
    resultado = await repo.obtener_por_reunion(reunion_id)

    assert resultado is not None
    assert resultado.reunion_id == reunion_id
    assert resultado.idioma == "es-CO"
    assert resultado.proveedor == "local"
    assert resultado.soporta_turnos is True
    assert len(resultado.turnos) == num_turnos

    for i, turno in enumerate(sorted(resultado.turnos, key=lambda t: t.orden)):
        assert turno.orden == i + 1
        assert turno.inicio_ms == i * 1000
        assert turno.fin_ms == (i + 1) * 1000


# ---------------------------------------------------------------------------
# Prueba por ejemplo — consulta sin transcripción (Task 7.4)
# Validates: Requirements 7.8
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_obtener_por_reunion_sin_transcripcion(
    session_factory: async_sessionmaker,
):
    """obtener_por_reunion devuelve None si no existe transcripción (sin error)."""
    repo = TranscripcionRepository(session_factory)
    resultado = await repo.obtener_por_reunion("inexistente-id")
    assert resultado is None
