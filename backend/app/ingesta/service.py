"""Servicio de ingesta — procesa la entrega de una Grabacion_De_Sesion desde cualquier origen.

El pipeline es idéntico sin importar si `origen_captura` es "extension_chrome" o
"bot_servidor". El campo se almacena para trazabilidad pero no altera el flujo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import GrabacionDeSesion, NotificacionDeGrabacion
from app.ingesta.schemas import DatosIngesta


async def procesar_ingesta(
    session: AsyncSession,
    datos: DatosIngesta,
    audio_ref: str,
    video_ref: str | None,
) -> tuple[GrabacionDeSesion, bool]:
    """Procesa una ingesta desde cualquier fuente de captura.

    1. Verifica idempotencia: si la clave ya existe, retorna la grabación existente.
    2. Crea la GrabacionDeSesion con origen_captura (NO altera el pipeline).
    3. Registra NotificacionDeGrabacion si notificacion_emitida_en está presente.
    4. Retorna tupla (GrabacionDeSesion, es_nueva).

    El campo origen_captura se almacena pero no cambia el comportamiento.
    El pipeline posterior (almacenar → transcribir → persistir) es idéntico
    para "extension_chrome" y "bot_servidor" (Req. 2.1, 2.2).

    Returns:
        Tupla (grabacion, es_nueva): es_nueva=True si se creó, False si ya existía
        (reintento idempotente).
    """
    # 1. Idempotencia — si la clave ya existe, retornar la grabación existente.
    stmt = select(GrabacionDeSesion).where(
        GrabacionDeSesion.clave_idempotencia == datos.clave_idempotencia
    )
    result = await session.execute(stmt)
    existente = result.scalar_one_or_none()
    if existente is not None:
        return existente, False

    # 2. Crear GrabacionDeSesion — origen_captura se almacena sin alterar flujo.
    ahora = datetime.now(UTC)
    grabacion = GrabacionDeSesion(
        id=str(uuid.uuid4()),
        reunion_id=datos.reunion_id,
        clave_idempotencia=datos.clave_idempotencia,
        origen_captura=datos.origen_captura,
        audio_ref=audio_ref,
        video_ref=video_ref,
        duracion_segundos=datos.duracion_segundos,
        interrumpida=datos.interrumpida,
        finalizada_en=ahora,
    )
    session.add(grabacion)

    # 3. Registrar NotificacionDeGrabacion si se proporcionó la marca.
    if datos.notificacion_emitida_en is not None:
        notificacion = NotificacionDeGrabacion(
            id=str(uuid.uuid4()),
            reunion_id=datos.reunion_id,
            emitida_en=datetime.fromisoformat(datos.notificacion_emitida_en),
        )
        session.add(notificacion)

    await session.flush()
    await session.refresh(grabacion)

    # 4. Retornar la grabación creada (es nueva).
    return grabacion, True
