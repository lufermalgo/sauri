"""Tests para el Worker_De_Transcripcion (worker.py).

# Feature: transcripcion-asr
Tasks: 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15, 8.16
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from hypothesis import given, HealthCheck, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import Reunion, Transcripcion, TurnoDeHabla
from app.reuniones.state_machine import (
    ESTADOS,
    ESTADOS_TERMINALES,
    TRANSICIONES_VALIDAS,
    aplicar_evento,
)
from app.transcripcion.motor_asr import (
    CapacidadesASR,
    OpcionesTranscripcion,
    ResultadoTranscripcion,
    SegmentoTranscripcion,
)
from app.transcripcion.worker import _procesar_transcripcion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_reunion_en_db(reunion_id: str, estado: str = "grabando") -> Reunion:
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


# ---------------------------------------------------------------------------
# Strategies for worker tests
# ---------------------------------------------------------------------------

invalid_mensaje_strategy = st.one_of(
    # Missing reunion_id
    st.fixed_dictionaries({"audio_ref": st.text(min_size=1, max_size=20)}),
    # Empty reunion_id
    st.fixed_dictionaries(
        {"reunion_id": st.just(""), "audio_ref": st.text(min_size=1, max_size=20)}
    ),
    # Only spaces reunion_id
    st.fixed_dictionaries(
        {"reunion_id": st.just("   "), "audio_ref": st.text(min_size=1, max_size=20)}
    ),
    # Missing audio_ref
    st.fixed_dictionaries({"reunion_id": st.uuids().map(str)}),
    # Empty audio_ref
    st.fixed_dictionaries({"reunion_id": st.uuids().map(str), "audio_ref": st.just("")}),
    # Only spaces audio_ref
    st.fixed_dictionaries(
        {"reunion_id": st.uuids().map(str), "audio_ref": st.just("  ")}
    ),
    # Empty dict
    st.just({}),
)

segment_strategy = st.fixed_dictionaries(
    {
        "texto": st.text(min_size=1, max_size=50),
        "inicio_ms": st.integers(min_value=0, max_value=10_000_000),
        "fin_ms": st.integers(min_value=0, max_value=10_000_000),
    }
).filter(lambda s: s["fin_ms"] >= s["inicio_ms"])


# ---------------------------------------------------------------------------
# Property 16: Entrada inválida no persiste ni lanza excepción (Task 8.6)
# Feature: transcripcion-asr, Property 16: Entrada inválida
# Validates: Requirements 1.3, 1.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(mensaje=invalid_mensaje_strategy)
@pytest.mark.asyncio
async def test_property_16_entrada_invalida_no_persiste(
    session_factory: async_sessionmaker, mensaje: dict
):
    """Mensaje inválido → termina sin excepción y sin persistir."""
    # Should not raise
    await _procesar_transcripcion(mensaje, session_factory)

    # No Transcripcion should exist
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcripcion))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Property 14: Corrección de la máquina de estados (Task 8.7)
# Feature: transcripcion-asr, Property 14: Máquina de estados
# Validates: Requirements 8.1, 8.2, 8.3, 8.5
# ---------------------------------------------------------------------------

# Generate all valid (estado, evento) pairs
valid_pairs = []
for estado, eventos in TRANSICIONES_VALIDAS.items():
    for evento in eventos:
        valid_pairs.append((estado, evento))

invalid_pairs = []
all_eventos = set()
for eventos in TRANSICIONES_VALIDAS.values():
    all_eventos.update(eventos.keys())
for estado in ESTADOS:
    transiciones = TRANSICIONES_VALIDAS.get(estado, {})
    for evento in all_eventos:
        if evento not in transiciones:
            invalid_pairs.append((estado, evento))


@given(pair=st.sampled_from(valid_pairs))
def test_property_14_transicion_valida(pair: tuple[str, str]):
    """Pares (estado, evento) válidos producen transiciones exitosas."""
    estado, evento = pair
    resultado = aplicar_evento(estado, evento)
    assert resultado.exitosa is True
    expected = TRANSICIONES_VALIDAS[estado][evento]
    assert resultado.nuevo_estado == expected


@given(pair=st.sampled_from(invalid_pairs))
def test_property_14_transicion_invalida(pair: tuple[str, str]):
    """Pares (estado, evento) inválidos producen exitosa=False."""
    estado, evento = pair
    resultado = aplicar_evento(estado, evento)
    assert resultado.exitosa is False
    assert resultado.nuevo_estado == estado


@given(estado=st.sampled_from(list(ESTADOS_TERMINALES)))
def test_property_14_estado_terminal_inmutable(estado: str):
    """Estados terminales son inmutables ante cualquier evento."""
    for evento in all_eventos:
        resultado = aplicar_evento(estado, evento)
        assert resultado.exitosa is False
        assert resultado.nuevo_estado == estado


# ---------------------------------------------------------------------------
# Property 15: Registro de historial en cada transición (Task 8.8)
# Feature: transcripcion-asr, Property 15: Historial
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pair=st.sampled_from(valid_pairs))
@pytest.mark.asyncio
async def test_property_15_historial_registrado(
    session_factory: async_sessionmaker, pair: tuple[str, str]
):
    """Cada transición válida crea un registro en EstadoHistorial."""
    from app.infra.models import EstadoHistorial
    from app.reuniones.service import registrar_transicion
    from sqlalchemy import select

    estado_inicial, evento = pair
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado=estado_inicial)
            session.add(reunion)

    async with session_factory() as session:
        async with session.begin():
            reunion = await session.get(Reunion, reunion_id)
            resultado = await registrar_transicion(session, reunion, evento)

    assert resultado.exitosa is True

    async with session_factory() as session:
        stmt = select(EstadoHistorial).where(
            EstadoHistorial.reunion_id == reunion_id
        )
        result = await session.execute(stmt)
        historiales = result.scalars().all()

    assert len(historiales) == 1
    assert historiales[0].estado == resultado.nuevo_estado


# ---------------------------------------------------------------------------
# Property 7: Mapeo de segmentos a turnos preserva orden y marcas (Task 8.9)
# Feature: transcripcion-asr, Property 7: Mapeo segmentos→turnos
# Validates: Requirements 5.5, 7.6
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    segmentos=st.lists(
        st.builds(
            SegmentoTranscripcion,
            texto=st.text(min_size=1, max_size=50),
            inicio_ms=st.integers(min_value=0, max_value=10_000_000),
            fin_ms=st.integers(min_value=0, max_value=10_000_000),
        ).filter(lambda s: s.fin_ms >= s.inicio_ms),
        min_size=1,
        max_size=10,
    )
)
@pytest.mark.asyncio
async def test_property_7_mapeo_segmentos_a_turnos(
    session_factory: async_sessionmaker,
    segmentos: list[SegmentoTranscripcion],
):
    """El worker mapea segmentos a turnos con orden ascendente por posición."""
    reunion_id = str(uuid.uuid4())

    # Setup: create reunion in grabando state
    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es-CO", soporta_turnos=True
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    # Verify turnos
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(TurnoDeHabla).where(
                TurnoDeHabla.transcripcion_id.in_(
                    select(Transcripcion.id).where(Transcripcion.reunion_id == reunion_id)
                )
            )
        )
        turnos = result.scalars().all()

    assert len(turnos) == len(segmentos)
    turnos_sorted = sorted(turnos, key=lambda t: t.orden)
    for i, turno in enumerate(turnos_sorted):
        assert turno.orden == i + 1
        assert turno.texto == segmentos[i].texto
        assert turno.inicio_ms == segmentos[i].inicio_ms
        assert turno.fin_ms == segmentos[i].fin_ms


# ---------------------------------------------------------------------------
# Property 9: Selección del idioma de la Transcripcion (Task 8.10)
# Feature: transcripcion-asr, Property 9: Selección idioma
# Validates: Requirements 6.3, 6.4
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    idioma_motor=st.one_of(
        st.just(None),
        st.just(""),
        st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=5,
        ),
    )
)
@pytest.mark.asyncio
async def test_property_9_seleccion_idioma(
    session_factory: async_sessionmaker, idioma_motor: str | None
):
    """idioma = resultado.idioma si no vacío, si no 'es-CO'."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    segmentos = [SegmentoTranscripcion(texto="hola", inicio_ms=0, fin_ms=1000)]
    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos,
        idioma=idioma_motor if idioma_motor else "",
        soporta_turnos=True,
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        trans = result.scalar_one_or_none()

    assert trans is not None
    if idioma_motor and idioma_motor.strip():
        assert trans.idioma == idioma_motor
    else:
        assert trans.idioma == "es-CO"


# ---------------------------------------------------------------------------
# Property 12: Registro de metadatos del proveedor (Task 8.11)
# Feature: transcripcion-asr, Property 12: Metadatos proveedor
# Validates: Requirements 7.5
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    es_local=st.booleans(),
    soporta_turnos=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_12_metadatos_proveedor(
    session_factory: async_sessionmaker,
    es_local: bool,
    soporta_turnos: bool,
):
    """La Transcripcion registra proveedor y soporta_turnos según capacidades."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    segmentos = [SegmentoTranscripcion(texto="test", inicio_ms=0, fin_ms=500)]
    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es", soporta_turnos=soporta_turnos
    )
    capacidades = CapacidadesASR(soporta_turnos=soporta_turnos, es_local=es_local)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        trans = result.scalar_one_or_none()

    assert trans is not None
    expected_proveedor = "local" if es_local else "cloud"
    assert trans.proveedor == expected_proveedor
    assert trans.soporta_turnos == soporta_turnos


# ---------------------------------------------------------------------------
# Property 8: Resultado sin segmentos no produce Transcripcion (Task 8.12)
# Feature: transcripcion-asr, Property 8: Sin segmentos
# Validates: Requirements 5.6, 7.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_8_sin_segmentos_no_persiste(
    session_factory: async_sessionmaker,
):
    """Lista vacía de segmentos → no se persiste Transcripcion, estado → fallido."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    resultado_asr = ResultadoTranscripcion(
        segmentos=[], idioma="es-CO", soporta_turnos=True
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcripcion))
        assert result.scalar_one_or_none() is None

        # Reunion should be in fallido
        reunion = await session.get(Reunion, reunion_id)
        assert reunion.estado_proceso == "fallido"


# ---------------------------------------------------------------------------
# Property 17: Fallo del motor se propaga sin persistir (Task 8.13)
# Feature: transcripcion-asr, Property 17: Fallo se propaga
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_17_fallo_motor_propaga(
    session_factory: async_sessionmaker,
):
    """Excepción del motor se propaga sin persistir Transcripcion."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    mock_motor = AsyncMock()
    mock_motor.transcribir.side_effect = RuntimeError("ASR engine crashed")

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        with pytest.raises(RuntimeError, match="ASR engine crashed"):
            await _procesar_transcripcion(mensaje, session_factory)

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(select(Transcripcion))
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Property 10: Unicidad de la Transcripcion por Reunion (Task 8.14)
# Feature: transcripcion-asr, Property 10: Unicidad
# Validates: Requirements 7.1, 9.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_10_unicidad_transcripcion(
    session_factory: async_sessionmaker,
):
    """Reprocesar el mismo mensaje no crea duplicados (UniqueConstraint)."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    segmentos = [SegmentoTranscripcion(texto="hola", inicio_ms=0, fin_ms=1000)]
    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es-CO", soporta_turnos=True
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    # First processing — succeeds
    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    # Second processing — should fail with IntegrityError (unique constraint)
    # Reset reunion state for the second attempt
    async with session_factory() as session:
        async with session.begin():
            reunion = await session.get(Reunion, reunion_id)
            reunion.estado_proceso = "grabando"

    from sqlalchemy.exc import IntegrityError

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        with pytest.raises(IntegrityError):
            await _procesar_transcripcion(mensaje, session_factory)

    # Still only one Transcripcion
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        transcripciones = result.scalars().all()

    assert len(transcripciones) == 1


# ---------------------------------------------------------------------------
# Property 11: Atomicidad de la persistencia (Task 8.15)
# Feature: transcripcion-asr, Property 11: Atomicidad
# Validates: Requirements 7.3, 7.4, 9.6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_11_atomicidad_rollback(
    session_factory: async_sessionmaker,
):
    """Fallo durante persistencia → rollback total sin parciales."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    segmentos = [SegmentoTranscripcion(texto="hola", inicio_ms=0, fin_ms=1000)]
    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es-CO", soporta_turnos=True
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    # Patch registrar_transicion to fail AFTER repo.crear is called
    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        with patch(
            "app.transcripcion.worker.registrar_transicion",
            side_effect=RuntimeError("DB failure during transition"),
        ):
            with pytest.raises(RuntimeError, match="DB failure"):
                await _procesar_transcripcion(mensaje, session_factory)

    # Verify: no Transcripcion or TurnoDeHabla persisted
    from sqlalchemy import select

    async with session_factory() as session:
        trans_result = await session.execute(select(Transcripcion))
        assert trans_result.scalar_one_or_none() is None

        turnos_result = await session.execute(select(TurnoDeHabla))
        assert turnos_result.scalars().all() == []


# ---------------------------------------------------------------------------
# Prueba por ejemplo — idioma prioritario por defecto (Task 8.16)
# Validates: Requirements 6.1, 6.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_idioma_prioritario_es_co(
    session_factory: async_sessionmaker,
):
    """El worker invoca al motor con idioma_prioritario='es-CO'."""
    reunion_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            reunion = _crear_reunion_en_db(reunion_id, estado="grabando")
            session.add(reunion)

    segmentos = [SegmentoTranscripcion(texto="test", inicio_ms=0, fin_ms=500)]
    resultado_asr = ResultadoTranscripcion(
        segmentos=segmentos, idioma="es-CO", soporta_turnos=True
    )
    capacidades = CapacidadesASR(soporta_turnos=True, es_local=True)

    mock_motor = AsyncMock()
    mock_motor.transcribir.return_value = resultado_asr
    mock_motor.capacidades = MagicMock(return_value=capacidades)

    mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}

    with patch("app.transcripcion.worker.crear_motor_asr", return_value=mock_motor):
        await _procesar_transcripcion(mensaje, session_factory)

    # Verify the motor was called with idioma_prioritario="es-CO"
    mock_motor.transcribir.assert_called_once()
    call_args = mock_motor.transcribir.call_args
    opciones = call_args[0][1]
    assert isinstance(opciones, OpcionesTranscripcion)
    assert opciones.idioma_prioritario == "es-CO"
