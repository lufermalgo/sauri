"""Property test de idempotencia de la ingesta por clave_idempotencia (service.py).

# Feature: meeting-capture-transcription, Property 14: Idempotencia de los manejadores del pipeline y de la ingesta
Task: 9.3 — Validates: Requirements 2.3, 4.1, 4.2

Task 9.4 (unit test): registro de Notificacion_De_Grabacion.
Validates: Requirements 6.5
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import GrabacionDeSesion, NotificacionDeGrabacion
from app.ingesta.schemas import DatosIngesta
from app.ingesta.service import procesar_ingesta


def _datos_ingesta(reunion_id: str, clave: str, notificacion: str | None = None) -> DatosIngesta:
    return DatosIngesta(
        reunion_id=reunion_id,
        clave_idempotencia=clave,
        origen_captura="extension_chrome",
        duracion_segundos=60,
        interrumpida=False,
        notificacion_emitida_en=notificacion,
    )


# ---------------------------------------------------------------------------
# Property 14 (faceta ingesta): Idempotencia de la ingesta
# Feature: meeting-capture-transcription, Property 14: Idempotencia de los manejadores del pipeline y de la ingesta
# Validates: Requirements 2.3, 4.1, 4.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_reintentos=st.integers(min_value=1, max_value=6))
@pytest.mark.asyncio
async def test_property_14_reintentos_misma_clave_no_duplican_grabacion(
    db_session: AsyncSession, n_reintentos: int
) -> None:
    """Reintentar la ingesta con la misma clave_idempotencia crea a lo sumo una GrabacionDeSesion."""
    reunion_id = str(uuid.uuid4())
    clave = str(uuid.uuid4())
    datos = _datos_ingesta(reunion_id, clave)

    resultados = []
    for i in range(n_reintentos):
        grabacion, es_nueva = await procesar_ingesta(
            db_session, datos, audio_ref=f"audio/{i}.webm", video_ref=None
        )
        await db_session.commit()
        resultados.append((grabacion, es_nueva))

    # Solo el primer intento debe ser "nuevo"
    assert resultados[0][1] is True
    assert all(es_nueva is False for _, es_nueva in resultados[1:])

    # Todas las llamadas devuelven la misma GrabacionDeSesion (mismo id)
    ids = {grabacion.id for grabacion, _ in resultados}
    assert len(ids) == 1

    result = await db_session.execute(
        select(GrabacionDeSesion).where(GrabacionDeSesion.clave_idempotencia == clave)
    )
    assert len(result.scalars().all()) == 1


# ---------------------------------------------------------------------------
# Task 9.4: registro auditable de Notificacion_De_Grabacion
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ejemplo_ingesta_registra_notificacion_de_grabacion(
    db_session: AsyncSession,
) -> None:
    """La ingesta persiste el registro auditable de consentimiento cuando se provee la marca."""
    reunion_id = str(uuid.uuid4())
    clave = str(uuid.uuid4())
    marca_emision = datetime.now(UTC).isoformat()
    datos = _datos_ingesta(reunion_id, clave, notificacion=marca_emision)

    await procesar_ingesta(db_session, datos, audio_ref="audio/x.webm", video_ref=None)
    await db_session.commit()

    result = await db_session.execute(
        select(NotificacionDeGrabacion).where(NotificacionDeGrabacion.reunion_id == reunion_id)
    )
    notificaciones = result.scalars().all()
    assert len(notificaciones) == 1


@pytest.mark.asyncio
async def test_ejemplo_ingesta_sin_marca_no_registra_notificacion(
    db_session: AsyncSession,
) -> None:
    """Sin notificacion_emitida_en, no se crea registro de NotificacionDeGrabacion."""
    reunion_id = str(uuid.uuid4())
    clave = str(uuid.uuid4())
    datos = _datos_ingesta(reunion_id, clave, notificacion=None)

    await procesar_ingesta(db_session, datos, audio_ref="audio/x.webm", video_ref=None)
    await db_session.commit()

    result = await db_session.execute(
        select(NotificacionDeGrabacion).where(NotificacionDeGrabacion.reunion_id == reunion_id)
    )
    assert result.scalars().all() == []
