"""Property tests del pipeline de transcripción para el spec meeting-capture-transcription.

# Feature: meeting-capture-transcription, Property 7: Invariante temporal de la Transcripcion
# Feature: meeting-capture-transcription, Property 8: Idioma de transcripción es-CO
# Feature: meeting-capture-transcription, Property 9: Intercambiabilidad del Motor_ASR
Tasks: 10.5, 10.6, 10.7
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import Reunion, Transcripcion, TurnoDeHabla
from app.transcripcion.motor_asr import (
    CapacidadesASR,
    MotorASR,
    OpcionesTranscripcion,
    ResultadoTranscripcion,
    SegmentoTranscripcion,
)
from app.transcripcion.worker import _procesar_transcripcion


def _crear_reunion_grabando(reunion_id: str) -> Reunion:
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


def _segmentos_no_solapados_strategy(max_segmentos: int = 8):
    """Genera listas de segmentos ordenados sin solape: fin_ms[i] <= inicio_ms[i+1]."""

    def _construir(gaps: list[int], duraciones: list[int]) -> list[SegmentoTranscripcion]:
        segmentos = []
        cursor = 0
        for gap, duracion in zip(gaps, duraciones, strict=True):
            inicio = cursor + gap
            fin = inicio + duracion
            segmentos.append(
                SegmentoTranscripcion(texto=f"seg-{len(segmentos)}", inicio_ms=inicio, fin_ms=fin)
            )
            cursor = fin
        return segmentos

    n = st.integers(min_value=1, max_value=max_segmentos)

    return n.flatmap(
        lambda k: st.tuples(
            st.lists(st.integers(min_value=0, max_value=500), min_size=k, max_size=k),
            st.lists(st.integers(min_value=0, max_value=5000), min_size=k, max_size=k),
        ).map(lambda pair: _construir(pair[0], pair[1]))
    )


# ---------------------------------------------------------------------------
# Property 7: Invariante temporal de la Transcripcion
# Feature: meeting-capture-transcription, Property 7: Invariante temporal de la Transcripcion
# Validates: Requirements 3.4, 3.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(segmentos=_segmentos_no_solapados_strategy())
@pytest.mark.asyncio
async def test_property_7_invariante_temporal_de_turnos_persistidos(
    session_factory: async_sessionmaker, segmentos: list[SegmentoTranscripcion]
) -> None:
    """Los TurnoDeHabla persistidos cumplen 0<=inicio_ms<=fin_ms, están ordenados y no se solapan."""
    reunion_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_crear_reunion_grabando(reunion_id))

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es-CO", soporta_turnos=True
    )
    mock_motor.capacidades = MagicMock(
        return_value=CapacidadesASR(soporta_turnos=True, es_local=True)
    )

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    async with session_factory() as session:
        result = await session.execute(
            select(TurnoDeHabla)
            .where(
                TurnoDeHabla.transcripcion_id.in_(
                    select(Transcripcion.id).where(Transcripcion.reunion_id == reunion_id)
                )
            )
            .order_by(TurnoDeHabla.orden)
        )
        turnos = result.scalars().all()

    assert len(turnos) == len(segmentos)

    # No hay identidad nominal en el TurnoDeHabla (sin campo de hablante)
    assert not hasattr(TurnoDeHabla, "hablante_id")
    assert not hasattr(TurnoDeHabla, "hablante")

    fin_anterior = None
    for turno in turnos:
        assert 0 <= turno.inicio_ms <= turno.fin_ms
        if fin_anterior is not None:
            assert turno.inicio_ms >= fin_anterior, "los turnos deben estar ordenados sin solape"
        fin_anterior = turno.fin_ms


# ---------------------------------------------------------------------------
# Property 8: Idioma de transcripción es-CO
# Feature: meeting-capture-transcription, Property 8: Idioma de transcripción es-CO
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    idioma_devuelto_por_motor=st.one_of(
        st.just(None),
        st.just(""),
        st.just("es-CO"),
    )
)
@pytest.mark.asyncio
async def test_property_8_opciones_fijan_es_co_y_transcripcion_registra_es_co(
    session_factory: async_sessionmaker, idioma_devuelto_por_motor: str | None
) -> None:
    """Las opciones de transcripción siempre fijan es-CO y la Transcripcion persistida registra es-CO."""
    reunion_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_crear_reunion_grabando(reunion_id))

    segmentos = [SegmentoTranscripcion(texto="hola", inicio_ms=0, fin_ms=500)]
    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = ResultadoTranscripcion(
        segmentos=segmentos, idioma=idioma_devuelto_por_motor, soporta_turnos=True
    )
    mock_motor.capacidades = MagicMock(
        return_value=CapacidadesASR(soporta_turnos=True, es_local=True)
    )

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    opciones_usadas: OpcionesTranscripcion = mock_motor.transcribir.call_args.args[1]
    assert opciones_usadas.idioma_prioritario == "es-CO"

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        transcripcion = result.scalar_one()

    assert transcripcion.idioma == "es-CO"


# ---------------------------------------------------------------------------
# Property 9: Intercambiabilidad del Motor_ASR
# Feature: meeting-capture-transcription, Property 9: Intercambiabilidad del Motor_ASR
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class _MotorASRConformeConTurnos(MotorASR):
    """Fake conforme con soporte de turnos (análogo a un proveedor local)."""

    async def transcribir(
        self, audio_ref: str, opciones: OpcionesTranscripcion
    ) -> ResultadoTranscripcion:
        return ResultadoTranscripcion(
            segmentos=[
                SegmentoTranscripcion(texto="uno", inicio_ms=0, fin_ms=100),
                SegmentoTranscripcion(texto="dos", inicio_ms=100, fin_ms=250),
            ],
            idioma="es-CO",
            soporta_turnos=True,
        )

    def capacidades(self) -> CapacidadesASR:
        return CapacidadesASR(soporta_turnos=True, es_local=True)


class _MotorASRConformeSinTurnos(MotorASR):
    """Fake conforme sin soporte de turnos (análogo a un proveedor cloud básico)."""

    async def transcribir(
        self, audio_ref: str, opciones: OpcionesTranscripcion
    ) -> ResultadoTranscripcion:
        return ResultadoTranscripcion(
            segmentos=[SegmentoTranscripcion(texto="texto único", inicio_ms=0, fin_ms=1000)],
            idioma="es-CO",
            soporta_turnos=False,
        )

    def capacidades(self) -> CapacidadesASR:
        return CapacidadesASR(soporta_turnos=False, es_local=False)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(motor_con_turnos=st.booleans())
@pytest.mark.asyncio
async def test_property_9_intercambiabilidad_de_motor_asr(
    session_factory: async_sessionmaker, motor_con_turnos: bool
) -> None:
    """Cualquier Motor_ASR conforme produce una Transcripcion válida sin cambios en el worker."""
    reunion_id = str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(_crear_reunion_grabando(reunion_id))

    motor: MotorASR = (
        _MotorASRConformeConTurnos() if motor_con_turnos else _MotorASRConformeSinTurnos()
    )

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}
    with patch("app.transcripcion.worker.crear_motor_asr", return_value=motor):
        await _procesar_transcripcion(mensaje, session_factory)

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        transcripcion = result.scalar_one()

        turnos_result = await session.execute(
            select(TurnoDeHabla)
            .where(TurnoDeHabla.transcripcion_id == transcripcion.id)
            .order_by(TurnoDeHabla.orden)
        )
        turnos = turnos_result.scalars().all()

    assert transcripcion.idioma == "es-CO"
    assert transcripcion.soporta_turnos == motor.capacidades().soporta_turnos
    assert len(turnos) >= 1
    fin_anterior = None
    for turno in turnos:
        assert 0 <= turno.inicio_ms <= turno.fin_ms
        if fin_anterior is not None:
            assert turno.inicio_ms >= fin_anterior
        fin_anterior = turno.fin_ms
