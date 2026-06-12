"""Tests para el Repositorio_De_Diarizacion (repository.py).

# Feature: identificacion-hablantes
Tasks: 11.1, 11.2, 11.3, 11.4, 11.5
Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.5, 10.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import (
    AsignacionDeHablante,
    Diarizacion,
    Hablante,
    Reunion,
    Transcripcion,
    TurnoDeHabla,
)
from app.diarizacion.repository import DiarizacionRepository


# ---------------------------------------------------------------------------
# Helpers — construyen el grafo de entidades reales (sin mocks)
# ---------------------------------------------------------------------------


def _crear_reunion(reunion_id: str) -> Reunion:
    return Reunion(
        id=reunion_id,
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso="completado",
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(timezone.utc),
    )


def _crear_transcripcion(reunion_id: str) -> Transcripcion:
    return Transcripcion(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        idioma="es-CO",
        proveedor="local",
        soporta_turnos=True,
        expira_en=None,
        creada_en=datetime.now(timezone.utc),
    )


def _crear_turnos(transcripcion_id: str, n: int) -> list[TurnoDeHabla]:
    return [
        TurnoDeHabla(
            id=str(uuid.uuid4()),
            transcripcion_id=transcripcion_id,
            texto=f"Texto turno {i+1}",
            inicio_ms=i * 1000,
            fin_ms=(i + 1) * 1000,
            orden=i + 1,
        )
        for i in range(n)
    ]


def _crear_diarizacion(
    reunion_id: str, transcripcion_id: str, num_hablantes: int, proveedor: str = "diar-engine-local"
) -> Diarizacion:
    return Diarizacion(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        transcripcion_id=transcripcion_id,
        proveedor=proveedor,
        num_hablantes=num_hablantes,
        estado_diarizacion="completada",
        causa_fallo=None,
        creada_en=datetime.now(timezone.utc),
        actualizada_en=datetime.now(timezone.utc),
    )


def _crear_hablantes(diarizacion_id: str, n: int) -> list[Hablante]:
    return [
        Hablante(
            id=str(uuid.uuid4()),
            diarizacion_id=diarizacion_id,
            etiqueta_cruda=f"SPEAKER_{i:02d}",
            etiqueta=f"Hablante {i+1}",
            orden=i + 1,
        )
        for i in range(n)
    ]


def _crear_asignaciones(
    diarizacion_id: str, turnos: list[TurnoDeHabla], hablantes: list[Hablante]
) -> list[AsignacionDeHablante]:
    asignaciones = []
    for i, turno in enumerate(turnos):
        hablante = hablantes[i % len(hablantes)]
        asignaciones.append(
            AsignacionDeHablante(
                id=str(uuid.uuid4()),
                diarizacion_id=diarizacion_id,
                turno_id=turno.id,
                hablante_id=hablante.id,
            )
        )
    return asignaciones


# ---------------------------------------------------------------------------
# Property 12: Unicidad de la Diarizacion por Reunion (Task 11.1)
# Feature: identificacion-hablantes, Property 12: Unicidad de la Diarizacion por Reunion
# Validates: Requirements 8.1, 10.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(intentos=st.integers(min_value=2, max_value=5))
@pytest.mark.asyncio
async def test_property_12_unicidad_diarizacion_por_reunion(
    session_factory: async_sessionmaker, intentos: int
):
    """Múltiples intentos de persistir Diarizacion para el mismo reunion_id no
    producen más de una Diarizacion (UniqueConstraint uq_diarizacion_reunion_id)."""
    reunion_id = str(uuid.uuid4())
    repo = DiarizacionRepository(session_factory)

    # Crear reunión y transcripción base
    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            transcripcion = _crear_transcripcion(reunion_id)
            session.add(transcripcion)
            transcripcion_id = transcripcion.id

    # Primer procesamiento: éxito
    async with session_factory() as session:
        async with session.begin():
            diar = _crear_diarizacion(reunion_id, transcripcion_id, num_hablantes=2)
            await repo.crear(session, diar, [], [])

    # Intentos adicionales del mismo reunion_id deben fallar por la constraint
    for _ in range(intentos - 1):
        with pytest.raises(Exception):
            async with session_factory() as session:
                async with session.begin():
                    diar_dup = _crear_diarizacion(reunion_id, transcripcion_id, num_hablantes=3)
                    await repo.crear(session, diar_dup, [], [])

    # Solo debe haber una Diarizacion para el reunion_id
    async with session_factory() as session:
        result = await session.execute(
            select(Diarizacion).where(Diarizacion.reunion_id == reunion_id)
        )
        diarizaciones = result.scalars().all()
    assert len(diarizaciones) == 1


# ---------------------------------------------------------------------------
# Property 13: Atomicidad de la persistencia (Task 11.2)
# Feature: identificacion-hablantes, Property 13: Atomicidad de la persistencia
# Validates: Requirements 8.2, 8.3, 10.6
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_hablantes=st.integers(min_value=1, max_value=5))
@pytest.mark.asyncio
async def test_property_13_atomicidad_persistencia(
    session_factory: async_sessionmaker, num_hablantes: int
):
    """Un fallo a mitad de escritura revierte toda la transacción: no quedan
    registros parciales (Diarizacion, Hablantes ni Asignaciones)."""
    reunion_id = str(uuid.uuid4())
    repo = DiarizacionRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            transcripcion = _crear_transcripcion(reunion_id)
            session.add(transcripcion)
            transcripcion_id = transcripcion.id

    # Inyectar fallo: dos Hablantes con el mismo PK viola la unicidad (PK),
    # restricción que SQLite y PostgreSQL aplican por igual → fuerza rollback.
    with pytest.raises(Exception):
        async with session_factory() as session:
            async with session.begin():
                diar = _crear_diarizacion(reunion_id, transcripcion_id, num_hablantes)
                hablantes = _crear_hablantes(diar.id, num_hablantes)
                pk_duplicado = hablantes[0].id
                hablante_colision = Hablante(
                    id=pk_duplicado,  # PK duplicado → IntegrityError en flush
                    diarizacion_id=diar.id,
                    etiqueta_cruda="SPEAKER_DUP",
                    etiqueta="Hablante dup",
                    orden=999,
                )
                await repo.crear(session, diar, hablantes + [hablante_colision], [])

    # Rollback total: no debe haber Diarizacion, Hablantes ni Asignaciones
    async with session_factory() as session:
        diar_count = (
            await session.execute(
                select(Diarizacion).where(Diarizacion.reunion_id == reunion_id)
            )
        ).scalars().all()
        hablante_count = (await session.execute(select(Hablante))).scalars().all()
        asignacion_count = (
            await session.execute(select(AsignacionDeHablante))
        ).scalars().all()

    assert len(diar_count) == 0
    assert len(hablante_count) == 0
    assert len(asignacion_count) == 0


# ---------------------------------------------------------------------------
# Property 14: Registro de metadatos del proveedor (Task 11.3)
# Feature: identificacion-hablantes, Property 14: Registro de metadatos del proveedor
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    num_hablantes=st.integers(min_value=0, max_value=8),
    proveedor=st.sampled_from(["diar-engine-local", "diarization-cloud"]),
)
@pytest.mark.asyncio
async def test_property_14_registro_metadatos_proveedor(
    session_factory: async_sessionmaker, num_hablantes: int, proveedor: str
):
    """La Diarizacion persiste proveedor y num_hablantes consistentes."""
    reunion_id = str(uuid.uuid4())
    repo = DiarizacionRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            transcripcion = _crear_transcripcion(reunion_id)
            session.add(transcripcion)
            transcripcion_id = transcripcion.id

    async with session_factory() as session:
        async with session.begin():
            diar = _crear_diarizacion(reunion_id, transcripcion_id, num_hablantes, proveedor)
            hablantes = _crear_hablantes(diar.id, num_hablantes)
            await repo.crear(session, diar, hablantes, [])

    recuperada = await repo.obtener_por_reunion(reunion_id)
    assert recuperada is not None
    assert recuperada.proveedor == proveedor
    assert recuperada.num_hablantes == num_hablantes
    assert len(recuperada.hablantes) == num_hablantes


# ---------------------------------------------------------------------------
# Property 15: Round-trip de persistencia y recuperación (Task 11.4)
# Feature: identificacion-hablantes, Property 15: Round-trip de persistencia y recuperación
# Validates: Requirements 8.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    num_hablantes=st.integers(min_value=1, max_value=5),
    num_turnos=st.integers(min_value=1, max_value=10),
)
@pytest.mark.asyncio
async def test_property_15_roundtrip_persistencia_recuperacion(
    session_factory: async_sessionmaker, num_hablantes: int, num_turnos: int
):
    """Persistir Diarizacion + Hablantes + Asignaciones y recuperar con
    obtener_por_reunion devuelve todo equivalente (selectinload)."""
    reunion_id = str(uuid.uuid4())
    repo = DiarizacionRepository(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            transcripcion = _crear_transcripcion(reunion_id)
            session.add(transcripcion)
            transcripcion_id = transcripcion.id
            turnos = _crear_turnos(transcripcion_id, num_turnos)
            for turno in turnos:
                session.add(turno)

    async with session_factory() as session:
        async with session.begin():
            diar = _crear_diarizacion(reunion_id, transcripcion_id, num_hablantes)
            hablantes = _crear_hablantes(diar.id, num_hablantes)
            asignaciones = _crear_asignaciones(diar.id, turnos, hablantes)
            await repo.crear(session, diar, hablantes, asignaciones)

    recuperada = await repo.obtener_por_reunion(reunion_id)
    assert recuperada is not None
    assert recuperada.reunion_id == reunion_id
    assert recuperada.transcripcion_id == transcripcion_id
    assert recuperada.estado_diarizacion == "completada"
    assert len(recuperada.hablantes) == num_hablantes
    assert len(recuperada.asignaciones) == num_turnos

    ordenes = sorted(h.orden for h in recuperada.hablantes)
    assert ordenes == list(range(1, num_hablantes + 1))


# ---------------------------------------------------------------------------
# Prueba por ejemplo — consulta sin Diarizacion (Task 11.5)
# Validates: Requirements 8.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_obtener_por_reunion_sin_diarizacion(
    session_factory: async_sessionmaker,
):
    """obtener_por_reunion devuelve None si no existe Diarizacion (sin error)."""
    repo = DiarizacionRepository(session_factory)
    resultado = await repo.obtener_por_reunion("inexistente-id")
    assert resultado is None
