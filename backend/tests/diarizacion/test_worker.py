"""Tests para el Worker_De_Diarizacion (worker.py).

# Feature: identificacion-hablantes
Tasks: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
Validates: Requirements 1.3, 1.4, 1.5, 1.6, 7.4, 7.5, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1

NOTA: Los mocks usados aquí simulan ÚNICAMENTE el Motor_De_Diarizacion (frontera
de I/O externa: diar-engine / servicio cloud) dentro de los tests. El código de
producción del worker es 100% real (AGENTS.md §3).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import (
    Diarizacion,
    GrabacionDeSesion,
    Hablante,
    Reunion,
    Transcripcion,
    TurnoDeHabla,
)
from app.diarizacion.motor_diarizacion import (
    CapacidadesDiarizacion,
    ResultadoDiarizacion,
    SegmentoDeHablante,
)
from app.diarizacion.worker import _procesar_diarizacion


# ---------------------------------------------------------------------------
# Helpers — construyen entidades reales en la DB de prueba
# ---------------------------------------------------------------------------


def _crear_reunion(reunion_id: str, estado: str = "completado") -> Reunion:
    return Reunion(
        id=reunion_id,
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso=estado,
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(timezone.utc),
    )


def _crear_grabacion(reunion_id: str, audio_ref: str = "audio/test.webm", duracion_segundos: int = 120) -> GrabacionDeSesion:
    return GrabacionDeSesion(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        clave_idempotencia=str(uuid.uuid4()),
        origen_captura="extension_chrome",
        audio_ref=audio_ref,
        video_ref=None,
        duracion_segundos=duracion_segundos,
        interrumpida=False,
        expira_en=None,
        finalizada_en=datetime.now(timezone.utc),
    )


def _crear_transcripcion_con_turnos(reunion_id: str, num_turnos: int) -> tuple[Transcripcion, list[TurnoDeHabla]]:
    t_id = str(uuid.uuid4())
    transcripcion = Transcripcion(
        id=t_id,
        reunion_id=reunion_id,
        idioma="es-CO",
        proveedor="local",
        soporta_turnos=True,
        expira_en=None,
        creada_en=datetime.now(timezone.utc),
    )
    turnos = [
        TurnoDeHabla(
            id=str(uuid.uuid4()),
            transcripcion_id=t_id,
            texto=f"Turno {i+1}",
            inicio_ms=i * 1000,
            fin_ms=(i + 1) * 1000,
            orden=i + 1,
        )
        for i in range(num_turnos)
    ]
    return transcripcion, turnos


async def _sembrar_reunion_completa(
    session_factory: async_sessionmaker,
    reunion_id: str,
    num_turnos: int = 3,
    estado_reunion: str = "completado",
) -> None:
    """Crea Reunion + GrabacionDeSesion + Transcripcion + Turnos en la DB."""
    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id, estado_reunion))
            session.add(_crear_grabacion(reunion_id))
            transcripcion, turnos = _crear_transcripcion_con_turnos(reunion_id, num_turnos)
            session.add(transcripcion)
            for turno in turnos:
                session.add(turno)


def _mock_motor(segmentos: list[SegmentoDeHablante], es_local: bool = True) -> AsyncMock:
    """Construye un mock del Motor_De_Diarizacion (frontera externa, solo en test)."""
    num = len({s.etiqueta_cruda for s in segmentos})
    motor = AsyncMock()
    motor.diarizar.return_value = ResultadoDiarizacion(segmentos=segmentos, num_hablantes=num)
    motor.capacidades = MagicMock(
        return_value=CapacidadesDiarizacion(
            es_local=es_local,
            nombre_proveedor="diar-engine-local" if es_local else "diarization-cloud",
        )
    )
    return motor


# ---------------------------------------------------------------------------
# Property 19: Entrada inválida / insumo ausente (Task 13.1)
# Feature: identificacion-hablantes, Property 19: Entrada inválida o insumo ausente
# Validates: Requirements 1.3, 1.4, 1.5, 1.6
# ---------------------------------------------------------------------------

_invalid_mensaje = st.one_of(
    st.just({}),
    st.just({"reunion_id": ""}),
    st.just({"reunion_id": "   "}),
    st.just({"reunion_id": None}),
    st.fixed_dictionaries({"reunion_id": st.integers()}),
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(mensaje=_invalid_mensaje)
@pytest.mark.asyncio
async def test_property_19_mensaje_invalido_no_persiste(
    session_factory: async_sessionmaker, mensaje: dict
):
    """reunion_id ausente/vacío/no-cadena → termina sin excepción y sin persistir."""
    await _procesar_diarizacion(mensaje, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarizacion))
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_property_19_reunion_inexistente_no_persiste(
    session_factory: async_sessionmaker,
):
    """reunion_id inexistente → ack sin persistir (Req 1.5)."""
    await _procesar_diarizacion({"reunion_id": str(uuid.uuid4())}, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarizacion))
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_property_19_sin_transcripcion_no_persiste(
    session_factory: async_sessionmaker,
):
    """Reunion sin Transcripcion → ack sin persistir (Req 1.6)."""
    reunion_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            session.add(_crear_grabacion(reunion_id))

    await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)
    async with session_factory() as session:
        result = await session.execute(select(Diarizacion))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Property 11: Resultado vacío → Diarizacion vacía válida (Task 13.2)
# Feature: identificacion-hablantes, Property 11: Resultado sin hablantes produce Diarizacion vacía válida
# Validates: Requirements 7.4, 7.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_11_resultado_vacio_diarizacion_completada(
    session_factory: async_sessionmaker,
):
    """Segmentos vacíos → Diarizacion completada con 0 hablantes y 0 asignaciones."""
    reunion_id = str(uuid.uuid4())
    await _sembrar_reunion_completa(session_factory, reunion_id, num_turnos=3)

    motor = _mock_motor(segmentos=[])
    with patch("app.diarizacion.worker.crear_motor_diarizacion", return_value=motor):
        await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarizacion).where(Diarizacion.reunion_id == reunion_id)
            )
        ).scalar_one_or_none()
        hablantes = (await session.execute(select(Hablante))).scalars().all()

    assert diar is not None
    assert diar.estado_diarizacion == "completada"
    assert diar.num_hablantes == 0
    assert len(hablantes) == 0


@pytest.mark.asyncio
async def test_property_11_sin_turnos_cero_asignaciones(
    session_factory: async_sessionmaker,
):
    """Transcripcion sin turnos → cero asignaciones aunque haya hablantes."""
    reunion_id = str(uuid.uuid4())
    await _sembrar_reunion_completa(session_factory, reunion_id, num_turnos=0)

    segmentos = [
        SegmentoDeHablante(etiqueta_cruda="SPEAKER_00", inicio_ms=0, fin_ms=5000),
        SegmentoDeHablante(etiqueta_cruda="SPEAKER_01", inicio_ms=5000, fin_ms=10000),
    ]
    motor = _mock_motor(segmentos=segmentos)
    with patch("app.diarizacion.worker.crear_motor_diarizacion", return_value=motor):
        await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)

    from app.infra.models import AsignacionDeHablante

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarizacion).where(Diarizacion.reunion_id == reunion_id)
            )
        ).scalar_one_or_none()
        asignaciones = (await session.execute(select(AsignacionDeHablante))).scalars().all()

    assert diar is not None
    assert diar.estado_diarizacion == "completada"
    assert diar.num_hablantes == 2
    assert len(asignaciones) == 0


# ---------------------------------------------------------------------------
# Property 20: Fallo del motor se propaga sin persistir completada (Task 13.3)
# Feature: identificacion-hablantes, Property 20: Fallo del motor se propaga sin persistir Diarizacion completada
# Validates: Requirements 9.3, 10.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_20_fallo_motor_propaga_sin_completada(
    session_factory: async_sessionmaker,
):
    """Excepción del motor → se propaga y no queda Diarizacion en 'completada'."""
    reunion_id = str(uuid.uuid4())
    await _sembrar_reunion_completa(session_factory, reunion_id, num_turnos=2)

    motor = AsyncMock()
    motor.diarizar.side_effect = RuntimeError("diar-engine crashed")
    motor.capacidades = MagicMock(
        return_value=CapacidadesDiarizacion(es_local=True, nombre_proveedor="diar-engine-local")
    )

    with patch("app.diarizacion.worker.crear_motor_diarizacion", return_value=motor):
        with pytest.raises(RuntimeError, match="diar-engine crashed"):
            await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)

    async with session_factory() as session:
        completadas = (
            await session.execute(
                select(Diarizacion).where(
                    Diarizacion.reunion_id == reunion_id,
                    Diarizacion.estado_diarizacion == "completada",
                )
            )
        ).scalars().all()
    assert len(completadas) == 0


# ---------------------------------------------------------------------------
# Property 18: Preservación del Estado_De_Proceso de la Reunion (Task 13.4)
# Feature: identificacion-hablantes, Property 18: Preservación del Estado_De_Proceso de la Reunion
# Validates: Requirements 9.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(estado_inicial=st.sampled_from(["en_cola", "grabando", "transcribiendo", "completado", "fallido"]))
@pytest.mark.asyncio
async def test_property_18_preserva_estado_proceso_reunion(
    session_factory: async_sessionmaker, estado_inicial: str
):
    """El Estado_De_Proceso de la Reunion permanece sin cambios tras diarizar."""
    reunion_id = str(uuid.uuid4())
    await _sembrar_reunion_completa(
        session_factory, reunion_id, num_turnos=2, estado_reunion=estado_inicial
    )

    segmentos = [SegmentoDeHablante(etiqueta_cruda="SPEAKER_00", inicio_ms=0, fin_ms=2000)]
    motor = _mock_motor(segmentos=segmentos)
    with patch("app.diarizacion.worker.crear_motor_diarizacion", return_value=motor):
        await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)

    async with session_factory() as session:
        reunion = await session.get(Reunion, reunion_id)
    assert reunion is not None
    assert reunion.estado_proceso == estado_inicial


# ---------------------------------------------------------------------------
# Property 17: Cada cambio de estado registra una marca UTC (Task 13.5)
# Feature: identificacion-hablantes, Property 17: Cada cambio de estado registra una marca UTC
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_17_marca_utc_en_estado_final(
    session_factory: async_sessionmaker,
):
    """La Diarizacion persistida registra actualizada_en en UTC."""
    reunion_id = str(uuid.uuid4())
    await _sembrar_reunion_completa(session_factory, reunion_id, num_turnos=1)

    segmentos = [SegmentoDeHablante(etiqueta_cruda="SPEAKER_00", inicio_ms=0, fin_ms=1000)]
    motor = _mock_motor(segmentos=segmentos)
    antes = datetime.now(timezone.utc)
    with patch("app.diarizacion.worker.crear_motor_diarizacion", return_value=motor):
        await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)
    despues = datetime.now(timezone.utc)

    async with session_factory() as session:
        diar = (
            await session.execute(
                select(Diarizacion).where(Diarizacion.reunion_id == reunion_id)
            )
        ).scalar_one_or_none()

    assert diar is not None
    assert diar.actualizada_en is not None
    actualizada = diar.actualizada_en
    if actualizada.tzinfo is None:
        actualizada = actualizada.replace(tzinfo=timezone.utc)
    assert antes <= actualizada <= despues


# ---------------------------------------------------------------------------
# Pruebas por ejemplo del worker (Task 13.6)
# Validates: Requirements 1.5, 1.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_reunion_inexistente_ack_sin_persistir(
    session_factory: async_sessionmaker,
):
    """Req 1.5: reunion_id inexistente → ack sin persistir (no excepción)."""
    await _procesar_diarizacion({"reunion_id": "no-existe"}, session_factory)
    async with session_factory() as session:
        assert (await session.execute(select(Diarizacion))).scalars().all() == []


@pytest.mark.asyncio
async def test_ejemplo_sin_transcripcion_ack_sin_persistir(
    session_factory: async_sessionmaker,
):
    """Req 1.6: Reunion sin Transcripcion → ack sin persistir (no excepción)."""
    reunion_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            session.add(_crear_reunion(reunion_id))
            session.add(_crear_grabacion(reunion_id))
    await _procesar_diarizacion({"reunion_id": reunion_id}, session_factory)
    async with session_factory() as session:
        assert (await session.execute(select(Diarizacion))).scalars().all() == []
