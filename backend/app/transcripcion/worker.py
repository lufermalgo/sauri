"""Worker de transcripción — consume la cola y produce Transcripciones.

Suscribe al tema "transcribir" de la ColaDeTrabajos. Para cada mensaje:
1. Crea un MotorASR vía la fábrica por configuración.
2. Invoca transcribir(audio_ref, idioma_prioritario="es-CO").
3. Si hay segmentos → persiste Transcripcion + TurnoDeHabla → transiciona a "completado".
4. Si no hay segmentos → transiciona a "fallido" con causa "fallo_del_motor".

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Reunion, Transcripcion, TurnoDeHabla
from app.infra.queue import ColaDeTrabajos
from app.reuniones.service import registrar_transicion
from app.transcripcion.factory import crear_motor_asr
from app.transcripcion.motor_asr import OpcionesTranscripcion
from app.transcripcion.repository import TranscripcionRepository

logger = logging.getLogger(__name__)


async def _procesar_transcripcion(
    mensaje: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    cola: ColaDeTrabajos | None = None,
) -> None:
    """Procesa un mensaje de la cola de transcripción.

    Args:
        mensaje: Esperado: {"reunion_id": str, "audio_ref": str}
        session_factory: Fábrica de sesiones async de SQLAlchemy.
        cola: ColaDeTrabajos opcional; si se provee, al quedar disponible la
            Transcripcion se publica un Mensaje_De_Diarizacion al tema
            "diarizar" con el reunion_id (Req. 1.2 de identificacion-hablantes).
    """
    # --- Validación del mensaje (Req. 1.2, 1.3) ---
    reunion_id = mensaje.get("reunion_id")
    audio_ref = mensaje.get("audio_ref")

    if not reunion_id or not isinstance(reunion_id, str) or not reunion_id.strip():
        logger.warning(
            "Mensaje descartado: reunion_id ausente o vacío. mensaje=%s", mensaje
        )
        return

    if not audio_ref or not isinstance(audio_ref, str) or not audio_ref.strip():
        logger.warning(
            "Mensaje descartado: audio_ref ausente o vacío. mensaje=%s", mensaje
        )
        return

    # --- Cargar Reunion (Req. 1.4) ---
    async with session_factory() as session:
        reunion = await session.get(Reunion, reunion_id)

    if reunion is None:
        logger.warning(
            "Mensaje descartado: Reunion no encontrada para reunion_id=%s",
            reunion_id,
        )
        return

    logger.info("Procesando transcripción para reunion_id=%s", reunion_id)

    # Transición inicial grabando → transcribiendo (Req. 8.1)
    async with session_factory() as session, session.begin():
        reunion = await session.get(Reunion, reunion_id)
        if reunion is None:
            logger.error("Reunion no encontrada: %s", reunion_id)
            return
        if reunion.estado_proceso == "grabando":
            await registrar_transicion(session, reunion, "grabacion_subida")

    # 1. Crear motor ASR vía fábrica (selecciona proveedor por config)
    motor = crear_motor_asr()

    # 2. Transcribir con idioma prioritario es-CO (Req. 3.2)
    # Excepciones del motor se propagan sin capturar (Req. 9.1)
    opciones = OpcionesTranscripcion(idioma_prioritario="es-CO")
    resultado = await motor.transcribir(audio_ref, opciones)

    # 3. Evaluar resultado y persistir
    transcripcion_creada = False
    async with session_factory() as session, session.begin():
        # Re-fetch reunion within the transaction for state transitions
        reunion = await session.get(Reunion, reunion_id)
        if reunion is None:
            logger.error("Reunion no encontrada: %s", reunion_id)
            return

        if resultado.segmentos:
            # Hay texto producido → persistir Transcripcion y turnos (Req. 3.4, 3.5)
            capacidades = motor.capacidades()

            transcripcion = Transcripcion(
                id=str(uuid.uuid4()),
                reunion_id=reunion_id,
                idioma=resultado.idioma or "es-CO",
                proveedor="local" if capacidades.es_local else "cloud",
                soporta_turnos=capacidades.soporta_turnos,
                expira_en=None,
                creada_en=datetime.now(UTC),
            )

            turnos = []
            for orden, segmento in enumerate(resultado.segmentos, start=1):
                turno = TurnoDeHabla(
                    id=str(uuid.uuid4()),
                    transcripcion_id=transcripcion.id,
                    texto=segmento.texto,
                    inicio_ms=segmento.inicio_ms,
                    fin_ms=segmento.fin_ms,
                    orden=orden,
                )
                turnos.append(turno)

            repo = TranscripcionRepository(session_factory)
            await repo.crear(session, transcripcion, turnos)
            transcripcion_creada = True

            # Transicionar a "completado" (Req. 3.6)
            transicion = await registrar_transicion(
                session, reunion, "transcripcion_completada"
            )

            if transicion.exitosa:
                logger.info(
                    "Transcripción completada para reunion_id=%s (%d segmentos)",
                    reunion_id,
                    len(resultado.segmentos),
                )
            else:
                logger.warning(
                    "Transición a completado rechazada para reunion_id=%s",
                    reunion_id,
                )
        else:
            # Sin texto pese a audio hablado → fallo del motor (Req. 3.7)
            transicion = await registrar_transicion(
                session, reunion, "fallo_motor"
            )

            if transicion.exitosa:
                logger.warning(
                    "Transcripción sin texto para reunion_id=%s → estado fallido",
                    reunion_id,
                )
            else:
                logger.warning(
                    "Transición a fallido rechazada para reunion_id=%s",
                    reunion_id,
                )

    # Encolar Mensaje_De_Diarizacion una vez confirmada la transacción de la
    # Transcripcion (Req. 1.2 de identificacion-hablantes). No altera el
    # Estado_De_Proceso de la Reunion (Req. 9.5).
    if cola is not None and transcripcion_creada:
        await cola.publicar("diarizar", {"reunion_id": reunion_id})
        logger.info(
            "Mensaje_De_Diarizacion encolado para reunion_id=%s (tema 'diarizar')",
            reunion_id,
        )


async def iniciar_worker(
    cola: ColaDeTrabajos,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Inicia el worker de transcripción: suscribe al tema 'transcribir'.

    Args:
        cola: Instancia de ColaDeTrabajos ya conectada.
        session_factory: Fábrica de sesiones SQLAlchemy para persistencia.
    """

    async def manejador(mensaje: dict[str, Any]) -> None:
        await _procesar_transcripcion(mensaje, session_factory, cola)

    await cola.suscribir("transcribir", manejador)
    logger.info("Worker de transcripción suscrito al tema 'transcribir'")
