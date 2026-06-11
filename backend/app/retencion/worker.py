"""Worker programado de borrado por retención (Req. 6.3, 6.6).

Elimina datos cuyo periodo de retención ha expirado:
- GrabacionDeSesion con expira_en <= now: borra audio + video del almacén
  y la Transcripcion asociada.
- Transcripcion con expira_en <= now (independientes): borra el registro.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import GrabacionDeSesion, Transcripcion
from app.infra.object_store import AlmacenDeObjetos

logger = logging.getLogger(__name__)


async def ejecutar_borrado_retencion(
    session: AsyncSession,
    almacen: AlmacenDeObjetos,
    now: datetime,
) -> None:
    """Ejecuta un ciclo de borrado de datos expirados.

    Pasos:
    a. Consulta GrabacionDeSesion con expira_en <= now.
    b. Para cada grabación expirada:
       - Elimina el blob de audio via almacen.eliminar(audio_ref).
       - Elimina el blob de video via almacen.eliminar(video_ref) si existe.
       - Elimina la Transcripcion asociada (por reunion_id).
       - Elimina el registro de GrabacionDeSesion.
    c. Consulta Transcripcion con expira_en <= now (independientemente expiradas).
    d. Elimina esos registros de Transcripcion.
    e. Commit.
    f. Logea cuántos registros se limpiaron.
    """
    grabaciones_borradas = 0
    transcripciones_borradas = 0

    # a. Consultar grabaciones expiradas
    result = await session.execute(
        select(GrabacionDeSesion).where(
            GrabacionDeSesion.expira_en.isnot(None),
            GrabacionDeSesion.expira_en <= now,
        )
    )
    grabaciones_expiradas = result.scalars().all()

    # b. Para cada grabación expirada
    for grabacion in grabaciones_expiradas:
        # Eliminar audio blob
        try:
            await almacen.eliminar(grabacion.audio_ref)
        except Exception:
            logger.warning(
                "No se pudo eliminar audio_ref=%s de grabacion=%s",
                grabacion.audio_ref,
                grabacion.id,
            )

        # Eliminar video blob si existe
        if grabacion.video_ref is not None:
            try:
                await almacen.eliminar(grabacion.video_ref)
            except Exception:
                logger.warning(
                    "No se pudo eliminar video_ref=%s de grabacion=%s",
                    grabacion.video_ref,
                    grabacion.id,
                )

        # Eliminar Transcripcion asociada (por reunion_id)
        result_trans = await session.execute(
            delete(Transcripcion).where(
                Transcripcion.reunion_id == grabacion.reunion_id
            )
        )
        transcripciones_borradas += result_trans.rowcount  # type: ignore[operator]

        # Eliminar el registro de GrabacionDeSesion
        await session.delete(grabacion)
        grabaciones_borradas += 1

    # c. Consultar transcripciones independientemente expiradas
    result_trans_independientes = await session.execute(
        select(Transcripcion).where(
            Transcripcion.expira_en.isnot(None),
            Transcripcion.expira_en <= now,
        )
    )
    transcripciones_independientes = result_trans_independientes.scalars().all()

    # d. Eliminar transcripciones independientemente expiradas
    for transcripcion in transcripciones_independientes:
        await session.delete(transcripcion)
        transcripciones_borradas += 1

    # e. Commit
    await session.commit()

    # f. Log de limpieza
    total = grabaciones_borradas + transcripciones_borradas
    if total > 0:
        logger.info(
            "Borrado por retención completado: %d grabaciones, %d transcripciones eliminadas",
            grabaciones_borradas,
            transcripciones_borradas,
        )
    else:
        logger.debug("Borrado por retención: sin datos expirados")


async def iniciar_worker_retencion(
    session_factory: async_sessionmaker[AsyncSession],
    almacen: AlmacenDeObjetos,
    intervalo_segundos: int = 3600,
) -> None:
    """Ejecuta el borrado por retención periódicamente.

    Corre indefinidamente, ejecutando ejecutar_borrado_retencion cada
    `intervalo_segundos` segundos.
    """
    logger.info(
        "Worker de retención iniciado (intervalo=%ds)", intervalo_segundos
    )
    while True:
        try:
            async with session_factory() as session:
                now = datetime.utcnow()
                await ejecutar_borrado_retencion(session, almacen, now)
        except Exception:
            logger.exception("Error en ciclo de borrado por retención")

        await asyncio.sleep(intervalo_segundos)
