"""Property test de intercambiabilidad de la fuente de captura (Asistente_De_Reunion).

# Feature: meeting-capture-transcription, Property 15: Intercambiabilidad de la fuente de captura
Task: 13.2 — Validates: Requirements 2.1, 2.2
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import GrabacionDeSesion
from app.ingesta.schemas import DatosIngesta
from app.ingesta.service import procesar_ingesta

ORIGENES = ["extension_chrome", "bot_servidor"]


# ---------------------------------------------------------------------------
# Property 15: Intercambiabilidad de la fuente de captura
# Feature: meeting-capture-transcription, Property 15: Intercambiabilidad de la fuente de captura
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    origen=st.sampled_from(ORIGENES),
    duracion_segundos=st.integers(min_value=0, max_value=36_000),
    interrumpida=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_15_pipeline_identico_independiente_del_origen(
    db_session: AsyncSession, origen: str, duracion_segundos: int, interrumpida: bool
) -> None:
    """El pipeline de ingesta produce el mismo resultado observable (estado, campos) sin
    importar si el origen es la extensión de Chrome o un bot servidor."""
    reunion_id = str(uuid.uuid4())
    datos = DatosIngesta(
        reunion_id=reunion_id,
        clave_idempotencia=str(uuid.uuid4()),
        origen_captura=origen,
        duracion_segundos=duracion_segundos,
        interrumpida=interrumpida,
        notificacion_emitida_en=None,
    )

    grabacion, es_nueva = await procesar_ingesta(
        db_session, datos, audio_ref="audio/x.webm", video_ref=None
    )
    await db_session.commit()

    assert es_nueva is True
    assert grabacion.reunion_id == reunion_id
    assert grabacion.duracion_segundos == duracion_segundos
    assert grabacion.interrumpida == interrumpida
    # origen_captura se registra para trazabilidad, sin alterar el resto del flujo
    assert grabacion.origen_captura == origen

    result = await db_session.execute(
        select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
    )
    persistida = result.scalar_one()
    assert persistida.audio_ref == grabacion.audio_ref
    assert persistida.video_ref == grabacion.video_ref


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(duracion_segundos=st.integers(min_value=0, max_value=36_000))
@pytest.mark.asyncio
async def test_property_15_ambos_origenes_producen_los_mismos_campos_persistidos(
    db_session: AsyncSession, duracion_segundos: int
) -> None:
    """Dos ingestas equivalentes que solo difieren en origen_captura producen los mismos
    campos persistidos (salvo el propio origen_captura y las claves)."""
    campos_por_origen: dict[str, GrabacionDeSesion] = {}

    for origen in ORIGENES:
        reunion_id = str(uuid.uuid4())
        datos = DatosIngesta(
            reunion_id=reunion_id,
            clave_idempotencia=str(uuid.uuid4()),
            origen_captura=origen,
            duracion_segundos=duracion_segundos,
            interrumpida=False,
            notificacion_emitida_en=None,
        )
        grabacion, _ = await procesar_ingesta(
            db_session, datos, audio_ref="audio/x.webm", video_ref=None
        )
        await db_session.commit()
        campos_por_origen[origen] = grabacion

    a = campos_por_origen["extension_chrome"]
    b = campos_por_origen["bot_servidor"]

    assert a.duracion_segundos == b.duracion_segundos
    assert a.interrumpida == b.interrumpida
    assert a.audio_ref == b.audio_ref
    assert a.video_ref == b.video_ref
