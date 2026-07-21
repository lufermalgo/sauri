"""Router de reuniones — rutas de registro, consulta y unión.

Expone:
- POST /api/v1/reuniones — registrar una reunión
- GET /api/v1/reuniones — listar reuniones del usuario autenticado
- GET /api/v1/reuniones/{reunion_id} — consultar estado de una reunión
- POST /api/v1/reuniones/{reunion_id}/solicitar-union — disparar unión manual
- GET /api/v1/reuniones/{reunion_id}/transcripcion — obtener transcripción

Todas las rutas requieren autenticación vía JWT.

Requirements: 4.5, 7.1, 7.2, 8.3, 8.4
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pydantic import BaseModel, Field

from app.auth.dependencies import obtener_usuario_actual
from app.auth.schemas import UsuarioAutenticado
from app.infra.database import create_engine, create_session_factory
from app.infra.models import Diarizacion, Reunion, Transcripcion, TurnoDeHabla
from app.infra.object_store import AlmacenDeObjetos, crear_almacen_de_objetos
from app.infra.queue import ColaDeTrabajos, crear_cola_de_trabajos
from app.reuniones.service import (
    consultar_reunion,
    eliminar_reunion,
    registrar_reunion,
    renombrar_reunion,
    solicitar_union,
)

router = APIRouter(prefix="/api/v1/reuniones", tags=["reuniones"])


def _obtener_cola() -> ColaDeTrabajos:
    """Factory de la cola de trabajos (DI simplificada)."""
    return crear_cola_de_trabajos()


def _obtener_almacen() -> AlmacenDeObjetos:
    """Factory del almacén de objetos (DI simplificada)."""
    return crear_almacen_de_objetos()


class EntradaRenombrar(BaseModel):
    """Cuerpo de PATCH /{reunion_id} — nuevo título de la nota."""

    titulo: str = Field(..., min_length=1, max_length=512)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_reunion(
    entrada: dict,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Registra una nueva reunión en estado 'en_cola'.

    Acepta enlace de Meet, invitación de calendario o solicitud manual.
    Requirements: 1.1, 1.7, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                reunion = await registrar_reunion(
                    session=session,
                    entrada=entrada,
                    creada_por=usuario.id,
                )
                return {
                    "reunion_id": reunion.id,
                    "estado_proceso": reunion.estado_proceso,
                    "enlace_meet": reunion.enlace_meet,
                    "origen": reunion.origen,
                }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    finally:
        await engine.dispose()


@router.get("/")
async def listar_reuniones(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> list[dict]:
    """Lista las reuniones del usuario autenticado.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stmt = (
                select(Reunion)
                .where(Reunion.creada_por == usuario.id)
                .order_by(Reunion.creada_en.desc())
            )
            result = await session.execute(stmt)
            reuniones = result.scalars().all()
            return [
                {
                    "reunion_id": r.id,
                    "enlace_meet": r.enlace_meet,
                    "origen": r.origen,
                    "estado_proceso": r.estado_proceso,
                    "causa_fallo": r.causa_fallo if r.estado_proceso == "fallido" else None,
                    "creada_en": r.creada_en.isoformat() if r.creada_en else None,
                    "titulo": r.titulo,
                }
                for r in reuniones
            ]
    finally:
        await engine.dispose()


@router.patch("/{reunion_id}")
async def renombrar_reunion_endpoint(
    reunion_id: str,
    entrada: EntradaRenombrar,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Renombra una nota (Mis_Notas → renombrar).

    Solo el usuario que creó la Reunion puede renombrarla.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                reunion = await session.get(Reunion, reunion_id)
                if reunion is None or reunion.creada_por != usuario.id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Reunión no encontrada: {reunion_id}",
                    )
                actualizada = await renombrar_reunion(session, reunion_id, entrada.titulo)
                assert actualizada is not None
                return {"reunion_id": actualizada.id, "titulo": actualizada.titulo}
    finally:
        await engine.dispose()


@router.delete("/{reunion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_reunion_endpoint(
    reunion_id: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> None:
    """Elimina una nota y todo lo asociado (Mis_Notas → eliminar).

    Solo el usuario que creó la Reunion puede eliminarla.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                reunion = await session.get(Reunion, reunion_id)
                if reunion is None or reunion.creada_por != usuario.id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Reunión no encontrada: {reunion_id}",
                    )
                almacen = _obtener_almacen()
                await eliminar_reunion(session, almacen, reunion_id)
    finally:
        await engine.dispose()


@router.get("/{reunion_id}")
async def obtener_reunion(
    reunion_id: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Consulta el estado actual de una reunión.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            resultado = await consultar_reunion(session, reunion_id)
            return resultado
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    finally:
        await engine.dispose()


@router.post("/{reunion_id}/solicitar-union")
async def solicitar_union_endpoint(
    reunion_id: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Solicita la unión manual del asistente a una reunión en cola.

    Requirements: 1.2, 9.1
    """
    cola = _obtener_cola()
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        await cola.conectar()
        async with session_factory() as session:
            async with session.begin():
                resultado = await solicitar_union(session, reunion_id, cola)
                if not resultado.exitosa:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"No se puede solicitar unión: la reunión está en estado "
                            f"'{resultado.nuevo_estado}'"
                        ),
                    )
                return {
                    "reunion_id": reunion_id,
                    "estado_proceso": resultado.nuevo_estado,
                }
    finally:
        await cola.desconectar()
        await engine.dispose()


@router.get("/{reunion_id}/transcripcion")
async def obtener_transcripcion(
    reunion_id: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Obtiene la transcripción completa de una reunión.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            # Verificar que la reunión existe
            reunion = await session.get(Reunion, reunion_id)
            if reunion is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Reunión no encontrada: {reunion_id}",
                )

            # Obtener la transcripción
            stmt = select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
            result = await session.execute(stmt)
            transcripcion = result.scalar_one_or_none()

            if transcripcion is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Transcripción no disponible para la reunión: {reunion_id}",
                )

            # Obtener los turnos/segmentos
            stmt_turnos = (
                select(TurnoDeHabla)
                .where(TurnoDeHabla.transcripcion_id == transcripcion.id)
                .order_by(TurnoDeHabla.orden)
            )
            result_turnos = await session.execute(stmt_turnos)
            turnos = result_turnos.scalars().all()

            return {
                "transcripcion_id": transcripcion.id,
                "reunion_id": transcripcion.reunion_id,
                "idioma": transcripcion.idioma,
                "proveedor": transcripcion.proveedor,
                "soporta_turnos": transcripcion.soporta_turnos,
                "creada_en": transcripcion.creada_en.isoformat() if transcripcion.creada_en else None,
                "segmentos": [
                    {
                        # Brecha aditiva (chrome-side-panel, Req. 8.1): expone el id
                        # del TurnoDeHabla para poder unirlo con su Asignacion_De_Hablante.
                        "id": t.id,
                        "texto": t.texto,
                        "inicio_ms": t.inicio_ms,
                        "fin_ms": t.fin_ms,
                        "orden": t.orden,
                    }
                    for t in turnos
                ],
            }
    finally:
        await engine.dispose()


@router.get("/{reunion_id}/diarizacion")
async def obtener_diarizacion(
    reunion_id: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
) -> dict:
    """Obtiene la Diarizacion (hablantes + asignaciones) de una reunión.

    Endpoint nuevo (chrome-side-panel, brecha de backend).
    Requirements: 6.3, 8.3, 10.1, 10.2, 14.1, 14.2
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            reunion = await session.get(Reunion, reunion_id)
            if reunion is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Reunión no encontrada: {reunion_id}",
                )

            stmt = (
                select(Diarizacion)
                .where(Diarizacion.reunion_id == reunion_id)
                .options(
                    selectinload(Diarizacion.hablantes),
                    selectinload(Diarizacion.asignaciones),
                )
            )
            result = await session.execute(stmt)
            diarizacion = result.scalar_one_or_none()

            if diarizacion is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Diarización no disponible para la reunión: {reunion_id}",
                )

            hablantes_ordenados = sorted(diarizacion.hablantes, key=lambda h: h.orden)

            return {
                "diarizacion_id": diarizacion.id,
                "reunion_id": diarizacion.reunion_id,
                "estado_diarizacion": diarizacion.estado_diarizacion,
                "num_hablantes": diarizacion.num_hablantes,
                "hablantes": [
                    {"id": h.id, "etiqueta": h.etiqueta, "orden": h.orden}
                    for h in hablantes_ordenados
                ],
                "asignaciones": [
                    {"turno_id": a.turno_id, "hablante_id": a.hablante_id}
                    for a in diarizacion.asignaciones
                ],
            }
    finally:
        await engine.dispose()
