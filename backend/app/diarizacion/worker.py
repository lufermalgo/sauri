"""Worker de diarización — consume la cola "diarizar" y produce Diarizaciones.

Suscribe al tema "diarizar" de la ColaDeTrabajos. Para cada mensaje:
1. Valida el reunion_id; carga Reunion, Transcripcion y GrabacionDeSesion.
2. Crea un MotorDiarizacion vía la fábrica por configuración.
3. Invoca diarizar(audio_ref, OpcionesDiarizacion(duracion_ms=...)).
4. Etiqueta hablantes y asigna turnos por máximo solape.
5. Persiste Diarizacion + Hablantes + Asignaciones en una transacción (estado completada).

NO modifica el Estado_De_Proceso de la Reunion (Req. 9.5): usa su propia máquina
de estados independiente (estado.py) y nunca invoca registrar_transicion.

Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 6.1, 7.1, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarizacion.asignacion import asignar_turnos
from app.diarizacion.estado import aplicar_evento_diarizacion
from app.diarizacion.etiquetado import etiquetar_hablantes
from app.diarizacion.factory import crear_motor_diarizacion
from app.diarizacion.motor_diarizacion import OpcionesDiarizacion
from app.diarizacion.repository import DiarizacionRepository
from app.infra.models import (
    AsignacionDeHablante,
    Diarizacion,
    GrabacionDeSesion,
    Hablante,
    Reunion,
)
from app.infra.queue import ColaDeTrabajos
from app.transcripcion.repository import TranscripcionRepository

logger = logging.getLogger(__name__)


async def _procesar_diarizacion(
    mensaje: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Procesa un Mensaje_De_Diarizacion del tema "diarizar".

    Args:
        mensaje: Esperado: {"reunion_id": str}
        session_factory: Fábrica de sesiones async de SQLAlchemy.
    """
    # --- Validación del mensaje (Req. 1.3, 1.4) ---
    reunion_id = mensaje.get("reunion_id")
    if not reunion_id or not isinstance(reunion_id, str) or not reunion_id.strip():
        logger.warning(
            "Mensaje de diarización descartado: reunion_id ausente o inválido. mensaje=%s",
            mensaje,
        )
        return

    # --- Cargar Reunion (Req. 1.5) ---
    async with session_factory() as session:
        reunion = await session.get(Reunion, reunion_id)
    if reunion is None:
        logger.warning(
            "Diarización descartada: Reunion no encontrada para reunion_id=%s",
            reunion_id,
        )
        return

    # --- Cargar Transcripcion + turnos (Req. 1.6) ---
    transcripcion_repo = TranscripcionRepository(session_factory)
    transcripcion = await transcripcion_repo.obtener_por_reunion(reunion_id)
    if transcripcion is None:
        logger.warning(
            "Diarización descartada: Transcripcion no encontrada para reunion_id=%s",
            reunion_id,
        )
        return

    # --- Cargar GrabacionDeSesion para audio_ref y duración ---
    async with session_factory() as session:
        grabacion = (
            await session.execute(
                select(GrabacionDeSesion).where(
                    GrabacionDeSesion.reunion_id == reunion_id
                )
            )
        ).scalar_one_or_none()
    if grabacion is None:
        logger.warning(
            "Diarización descartada: GrabacionDeSesion no encontrada para reunion_id=%s",
            reunion_id,
        )
        return

    logger.info("Procesando diarización para reunion_id=%s", reunion_id)

    # --- Estado: pendiente → en_proceso (Req. 9.1) ---
    transicion = aplicar_evento_diarizacion("pendiente", "iniciar_proceso")
    estado_actual = transicion.nuevo_estado  # "en_proceso"

    # --- Crear motor (Req. 2) ---
    motor = crear_motor_diarizacion()

    # --- Diarizar (Req. 10.1: excepción del motor se propaga sin persistir) ---
    duracion_ms = grabacion.duracion_segundos * 1000
    resultado = await motor.diarizar(
        grabacion.audio_ref, OpcionesDiarizacion(duracion_ms=duracion_ms)
    )

    # --- Etiquetar hablantes (Req. 6) y asignar turnos (Req. 7) ---
    hablantes_dominio = etiquetar_hablantes(resultado.segmentos)
    asignaciones_dominio = asignar_turnos(
        list(transcripcion.turnos), resultado.segmentos, hablantes_dominio
    )

    # --- Estado: en_proceso → completada (Req. 9.2, 9.4) ---
    transicion_final = aplicar_evento_diarizacion(estado_actual, "diarizacion_completada")
    ahora_utc = datetime.now(timezone.utc)

    capacidades = motor.capacidades()

    # --- Construir entidades ORM ---
    diarizacion_id = str(uuid.uuid4())
    diarizacion = Diarizacion(
        id=diarizacion_id,
        reunion_id=reunion_id,
        transcripcion_id=transcripcion.id,
        proveedor=capacidades.nombre_proveedor,
        num_hablantes=resultado.num_hablantes,
        estado_diarizacion=transicion_final.nuevo_estado,  # "completada"
        causa_fallo=transicion_final.causa_fallo,  # None en éxito
        creada_en=ahora_utc,
        actualizada_en=ahora_utc,
    )

    # Mapear Hablantes de dominio → ORM, indexados por etiqueta_cruda
    hablantes_orm: list[Hablante] = []
    hablante_id_por_etiqueta: dict[str, str] = {}
    for hablante in hablantes_dominio:
        h_id = str(uuid.uuid4())
        hablante_id_por_etiqueta[hablante.etiqueta_cruda] = h_id
        hablantes_orm.append(
            Hablante(
                id=h_id,
                diarizacion_id=diarizacion_id,
                etiqueta_cruda=hablante.etiqueta_cruda,
                etiqueta=hablante.etiqueta,
                orden=hablante.orden,
            )
        )

    # Mapear asignaciones de dominio → ORM
    asignaciones_orm: list[AsignacionDeHablante] = []
    for turno_id, hablante in asignaciones_dominio:
        asignaciones_orm.append(
            AsignacionDeHablante(
                id=str(uuid.uuid4()),
                diarizacion_id=diarizacion_id,
                turno_id=turno_id,
                hablante_id=hablante_id_por_etiqueta[hablante.etiqueta_cruda],
            )
        )

    # --- Persistir en una única transacción (Req. 8.2) ---
    repo = DiarizacionRepository(session_factory)
    async with session_factory() as session:
        async with session.begin():
            await repo.crear(session, diarizacion, hablantes_orm, asignaciones_orm)

    logger.info(
        "Diarización completada para reunion_id=%s (%d hablantes, %d asignaciones)",
        reunion_id,
        len(hablantes_orm),
        len(asignaciones_orm),
    )


async def iniciar_worker(
    cola: ColaDeTrabajos,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Inicia el worker de diarización: suscribe al tema 'diarizar' (Req. 1.1).

    Args:
        cola: Instancia de ColaDeTrabajos ya conectada.
        session_factory: Fábrica de sesiones SQLAlchemy para persistencia.
    """

    async def manejador(mensaje: dict[str, Any]) -> None:
        await _procesar_diarizacion(mensaje, session_factory)

    await cola.suscribir("diarizar", manejador)
    logger.info("Worker de diarización suscrito al tema 'diarizar'")
