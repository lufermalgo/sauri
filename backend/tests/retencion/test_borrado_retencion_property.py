"""Property test del borrado por retención del dato completo (worker.py).

# Feature: meeting-capture-transcription, Property 12: Borrado por retención del dato completo
Task: 12.4 — Validates: Requirements 6.3, 6.6
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import GrabacionDeSesion, Reunion, Transcripcion
from app.infra.object_store import AlmacenDeObjetos
from app.retencion.worker import ejecutar_borrado_retencion


class _AlmacenFake(AlmacenDeObjetos):
    """Fake en memoria de AlmacenDeObjetos para pruebas."""

    def __init__(self) -> None:
        self._objetos: dict[str, bytes] = {}

    async def guardar(self, clave: str, contenido: bytes, content_type: str = "application/octet-stream") -> str:
        self._objetos[clave] = contenido
        return clave

    async def obtener(self, referencia: str) -> bytes:
        return self._objetos[referencia]

    async def eliminar(self, referencia: str) -> None:
        self._objetos.pop(referencia, None)

    async def url_temporal_de_lectura(self, referencia: str, ttl_seconds: int = 3600) -> str:
        return f"https://example.local/{referencia}?ttl={ttl_seconds}"

    def existe(self, referencia: str) -> bool:
        return referencia in self._objetos


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
        creada_en=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 12: Borrado por retención del dato completo
# Feature: meeting-capture-transcription, Property 12: Borrado por retención del dato completo
# Validates: Requirements 6.3, 6.6
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tiene_video=st.booleans())
@pytest.mark.asyncio
async def test_property_12_borrado_elimina_audio_video_y_transcripcion(
    db_session: AsyncSession, tiene_video: bool
) -> None:
    """Al borrar una Grabacion expirada, se expira su audio, su video (si existe) y su Transcripcion asociada."""
    reunion_id = str(uuid.uuid4())
    almacen = _AlmacenFake()

    audio_ref = f"audio/{uuid.uuid4()}.webm"
    video_ref = f"video/{uuid.uuid4()}.webm" if tiene_video else None
    await almacen.guardar(audio_ref, b"audio-bytes")
    if video_ref:
        await almacen.guardar(video_ref, b"video-bytes")

    ahora = datetime.now(UTC)
    db_session.add(_crear_reunion(reunion_id))
    db_session.add(
        GrabacionDeSesion(
            id=str(uuid.uuid4()),
            reunion_id=reunion_id,
            clave_idempotencia=str(uuid.uuid4()),
            origen_captura="extension_chrome",
            audio_ref=audio_ref,
            video_ref=video_ref,
            duracion_segundos=60,
            interrumpida=False,
            expira_en=ahora - timedelta(seconds=1),
            finalizada_en=ahora - timedelta(days=91),
        )
    )
    db_session.add(
        Transcripcion(
            id=str(uuid.uuid4()),
            reunion_id=reunion_id,
            idioma="es-CO",
            proveedor="local",
            soporta_turnos=True,
            expira_en=None,
            creada_en=ahora - timedelta(days=91),
        )
    )
    await db_session.commit()

    await ejecutar_borrado_retencion(db_session, almacen, ahora)

    assert not almacen.existe(audio_ref)
    if video_ref:
        assert not almacen.existe(video_ref)

    result_grabacion = await db_session.execute(
        select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
    )
    assert result_grabacion.scalar_one_or_none() is None

    result_transcripcion = await db_session.execute(
        select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
    )
    assert result_transcripcion.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_property_12_no_expirados_se_conservan(db_session: AsyncSession) -> None:
    """Grabaciones y Transcripciones sin expirar no se tocan."""
    reunion_id = str(uuid.uuid4())
    almacen = _AlmacenFake()
    ahora = datetime.now(UTC)

    audio_ref = f"audio/{uuid.uuid4()}.webm"
    await almacen.guardar(audio_ref, b"audio-bytes")

    db_session.add(_crear_reunion(reunion_id))
    db_session.add(
        GrabacionDeSesion(
            id=str(uuid.uuid4()),
            reunion_id=reunion_id,
            clave_idempotencia=str(uuid.uuid4()),
            origen_captura="extension_chrome",
            audio_ref=audio_ref,
            video_ref=None,
            duracion_segundos=60,
            interrumpida=False,
            expira_en=ahora + timedelta(days=1),
            finalizada_en=ahora,
        )
    )
    await db_session.commit()

    await ejecutar_borrado_retencion(db_session, almacen, ahora)

    assert almacen.existe(audio_ref)
    result = await db_session.execute(
        select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
    )
    assert result.scalar_one_or_none() is not None
