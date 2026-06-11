"""Router de ingesta — endpoint de subida de Grabacion_De_Sesion multipart autenticado.

Recibe A/V multipart + metadatos JSON (DatosIngesta), exige autenticación,
persiste en AlmacenDeObjetos, registra NotificacionDeGrabacion, transiciona
la Reunion a "transcribiendo" y encola el trabajo de transcripción.

Requirements: 2.2, 6.5, 9.1, 9.2
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.auth.dependencies import obtener_usuario_actual
from app.auth.schemas import UsuarioAutenticado
from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import AlmacenDeObjetos, crear_almacen_de_objetos
from app.infra.queue import ColaDeTrabajos, crear_cola_de_trabajos
from app.ingesta.schemas import DatosIngesta
from app.ingesta.service import procesar_ingesta
from app.reuniones.service import registrar_transicion

router = APIRouter(prefix="/api/v1/ingesta", tags=["ingesta"])


def _obtener_almacen() -> AlmacenDeObjetos:
    """Crea la instancia del almacén de objetos (DI simplificada, wiring final en task 17.1)."""
    return crear_almacen_de_objetos()


def _obtener_cola() -> ColaDeTrabajos:
    """Crea la instancia de la cola de trabajos (DI simplificada, wiring final en task 17.1)."""
    return crear_cola_de_trabajos()


@router.post("/subir", status_code=status.HTTP_200_OK)
async def subir_grabacion(
    audio: UploadFile = File(...),
    video: UploadFile | None = File(None),
    datos: str = Form(...),
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Endpoint de subida multipart autenticado para Grabacion_De_Sesion.

    Flujo:
    a. Parsea `datos` JSON en DatosIngesta.
    b. Valida autenticación vía dependency (obtener_usuario_actual).
    c. Almacena audio en AlmacenDeObjetos → audio_ref.
    d. Almacena video en AlmacenDeObjetos (si se provee) → video_ref.
    e. Llama a procesar_ingesta (crea GrabacionDeSesion, maneja idempotencia).
    f. Transiciona la Reunion a "transcribiendo" vía registrar_transicion.
    g. Encola trabajo de transcripción.
    h. Retorna 200 con ID de la grabación y estado.
    """
    # a. Parsear JSON de datos
    try:
        datos_dict = json.loads(datos)
        datos_ingesta = DatosIngesta(**datos_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Datos de ingesta inválidos: {exc}",
        )

    # b. Autenticación ya validada por la dependency

    # Obtener infraestructura
    almacen = _obtener_almacen()
    cola = _obtener_cola()

    # c. Almacenar audio en AlmacenDeObjetos
    audio_content = await audio.read()
    audio_key = f"grabaciones/{datos_ingesta.reunion_id}/{uuid.uuid4()}/audio"
    audio_ref = await almacen.guardar(
        clave=audio_key,
        contenido=audio_content,
        content_type=audio.content_type or "audio/webm",
    )

    # d. Almacenar video (opcional)
    video_ref: str | None = None
    if video is not None:
        video_content = await video.read()
        video_key = f"grabaciones/{datos_ingesta.reunion_id}/{uuid.uuid4()}/video"
        video_ref = await almacen.guardar(
            clave=video_key,
            contenido=video_content,
            content_type=video.content_type or "video/webm",
        )

    # e. Procesar ingesta (crear GrabacionDeSesion, idempotencia, notificación)
    engine = create_engine()
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        async with session.begin():
            grabacion, es_nueva = await procesar_ingesta(
                session=session,
                datos=datos_ingesta,
                audio_ref=audio_ref,
                video_ref=video_ref,
            )

            # Si es un reintento idempotente (clave duplicada), retornar sin
            # transicionar ni encolar de nuevo (Req. 2.3, 4.1, 4.2).
            if not es_nueva:
                await engine.dispose()
                return {
                    "grabacion_id": grabacion.id,
                    "estado": "duplicado_idempotente",
                }

            # f. Transicionar Reunion a "transcribiendo"
            from app.infra.models import Reunion

            reunion = await session.get(Reunion, datos_ingesta.reunion_id)
            if reunion is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Reunion no encontrada: {datos_ingesta.reunion_id}",
                )

            resultado_transicion = await registrar_transicion(
                session=session,
                reunion=reunion,
                evento="grabacion_subida",
            )

    # g. Encolar trabajo de transcripción (solo si la grabación es nueva)
    await cola.conectar()
    try:
        await cola.publicar(
            tema="transcribir",
            mensaje={
                "reunion_id": datos_ingesta.reunion_id,
                "audio_ref": audio_ref,
            },
        )
    finally:
        await cola.desconectar()

    # Cerrar el engine
    await engine.dispose()

    # h. Retornar resultado
    return {
        "grabacion_id": grabacion.id,
        "estado": "transcribiendo" if resultado_transicion.exitosa else reunion.estado_proceso,
    }
