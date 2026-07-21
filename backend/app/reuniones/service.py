"""Servicio de reuniones — capa de persistencia para transiciones de estado y registro.

Este módulo implementa:
- `registrar_transicion`: usa la función pura `aplicar_evento` para computar la
  transición y luego persiste el resultado (actualiza la Reunion y crea una fila
  en EstadoHistorial).
- `registrar_reunion`: acepta los tres tipos de entrada (enlace, calendario, manual),
  valida el enlace de Meet, crea la Reunion en estado 'en_cola' y registra la entrada
  inicial en EstadoHistorial.
- `consultar_reunion`: devuelve el estado actual de una Reunion y, si aplica, la
  causa de fallo.

Requirements: 1.1, 1.4, 1.5, 1.7, 2.5, 3.6, 4.1, 4.2, 4.4, 4.5
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Diarizacion, EstadoHistorial, GrabacionDeSesion, Reunion
from app.infra.object_store import AlmacenDeObjetos
from app.infra.queue import ColaDeTrabajos
from app.reuniones.schemas import (
    EntradaReunionCalendario,
    EntradaReunionEnlace,
    EntradaReunionManual,
)
from app.reuniones.state_machine import ResultadoTransicion, aplicar_evento


async def registrar_transicion(
    session: AsyncSession,
    reunion: Reunion,
    evento: str,
) -> ResultadoTransicion:
    """Aplica un evento vía la función pura y persiste la transición.

    Si la transición es válida:
    1. Actualiza `reunion.estado_proceso` (y `causa_fallo` si aplica).
    2. Crea una entrada en `EstadoHistorial` con marca de tiempo.
    3. Hace flush (sin commit — el llamador controla la transacción).

    Si la transición es inválida: no modifica nada, retorna exitosa=False.

    Args:
        session: Sesión async de SQLAlchemy (el llamador maneja commit/rollback).
        reunion: Instancia de Reunion con su estado actual.
        evento: Evento de dominio a aplicar.

    Returns:
        ResultadoTransicion con el resultado de la operación.
    """
    resultado = aplicar_evento(reunion.estado_proceso, evento)

    if not resultado.exitosa:
        return resultado

    # Actualizar el estado de la reunión
    reunion.estado_proceso = resultado.nuevo_estado
    if resultado.causa_fallo is not None:
        reunion.causa_fallo = resultado.causa_fallo

    # Crear entrada en el historial de estados
    historial = EstadoHistorial(
        id=str(uuid.uuid4()),
        reunion_id=reunion.id,
        estado=resultado.nuevo_estado,
        causa_fallo=resultado.causa_fallo,
        ocurrido_en=datetime.now(UTC),
    )
    session.add(historial)

    await session.flush()

    return resultado


async def registrar_reunion(
    session: AsyncSession,
    entrada: dict,
    creada_por: str,
) -> Reunion:
    """Crea una nueva Reunion en estado 'en_cola' a partir de una entrada validada.

    Determina el 'origen' a partir de la forma de la entrada:
    - Tiene `id_invitacion_calendario` → 'invitacion_calendario'
    - Solo `enlace_meet` → 'enlace' (por defecto para EntradaReunionEnlace)
    - Solo `enlace_meet` como solicitud manual → 'manual'

    Dado que EntradaReunionEnlace y EntradaReunionManual tienen la misma forma,
    se acepta un campo extra `tipo` con valor 'manual' para distinguirlos.
    Si no está presente, se asume 'enlace'.

    Valida el formato del enlace_meet. Crea la Reunion y la entrada inicial
    en EstadoHistorial.

    Raises:
        ValueError: Si la entrada es inválida (enlace no válido, campos faltantes).

    Requirements: 1.1, 1.7
    """
    # Determinar el tipo de entrada y validar con Pydantic
    try:
        if "id_invitacion_calendario" in entrada:
            modelo = EntradaReunionCalendario(**entrada)
            origen = "invitacion_calendario"
        elif entrada.get("tipo") == "manual":
            # Excluir el campo 'tipo' para la validación Pydantic
            datos_validacion = {k: v for k, v in entrada.items() if k != "tipo"}
            modelo = EntradaReunionManual(**datos_validacion)
            origen = "manual"
        else:
            modelo = EntradaReunionEnlace(**entrada)
            origen = "enlace"
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"Entrada inválida: {exc}") from exc

    ahora = datetime.now(UTC)
    reunion_id = str(uuid.uuid4())

    # Crear la Reunion en estado 'en_cola'
    reunion = Reunion(
        id=reunion_id,
        enlace_meet=modelo.enlace_meet,
        origen=origen,
        id_invitacion_calendario=(
            modelo.id_invitacion_calendario
            if isinstance(modelo, EntradaReunionCalendario)
            else None
        ),
        hora_inicio_programada=(
            modelo.hora_inicio_programada
            if isinstance(modelo, EntradaReunionCalendario)
            else None
        ),
        estado_proceso="en_cola",
        causa_fallo=None,
        creada_por=creada_por,
        creada_en=ahora,
    )
    session.add(reunion)
    # Flush the Reunion first: EstadoHistorial's FK requires the parent row
    # to exist before insert (enforced by real databases, not by the SQLite
    # test engine, which ignores foreign keys by default).
    await session.flush()

    # Crear entrada inicial en EstadoHistorial
    historial = EstadoHistorial(
        id=str(uuid.uuid4()),
        reunion_id=reunion_id,
        estado="en_cola",
        causa_fallo=None,
        ocurrido_en=ahora,
    )
    session.add(historial)
    await session.flush()

    return reunion


async def consultar_reunion(
    session: AsyncSession,
    reunion_id: str,
) -> dict:
    """Consulta el estado actual de una Reunion.

    Returns a dict with:
    - reunion_id
    - estado_proceso: the current state (from reunion.estado_proceso)
    - causa_fallo: included ONLY if estado_proceso == "fallido", None otherwise

    Raises ValueError if reunion not found.

    Requirements: 4.5
    """
    reunion = await session.get(Reunion, reunion_id)

    if reunion is None:
        raise ValueError(f"Reunion no encontrada: {reunion_id}")

    resultado: dict = {
        "reunion_id": reunion.id,
        "titulo": reunion.titulo,
        "estado_proceso": reunion.estado_proceso,
    }

    if reunion.estado_proceso == "fallido":
        resultado["causa_fallo"] = reunion.causa_fallo

    return resultado


async def renombrar_reunion(
    session: AsyncSession,
    reunion_id: str,
    nuevo_titulo: str,
) -> Reunion | None:
    """Renombra una Reunion (Mis_Notas → renombrar nota).

    Retorna None si la Reunion no existe; el llamador decide cómo mapear
    eso a una respuesta HTTP (404).
    """
    reunion = await session.get(Reunion, reunion_id)
    if reunion is None:
        return None

    reunion.titulo = nuevo_titulo
    await session.flush()
    return reunion


async def eliminar_reunion(
    session: AsyncSession,
    almacen: AlmacenDeObjetos,
    reunion_id: str,
) -> bool:
    """Elimina una Reunion y todo lo asociado (Mis_Notas → eliminar nota).

    Orden necesario porque `diarizaciones.reunion_id` y
    `diarizaciones.transcripcion_id` no tienen ondelete=CASCADE (bloquearían
    el borrado en cascada de transcripciones/turnos_de_habla si quedara una
    Diarizacion referenciándolos):
    1. Borra la Diarizacion de esta reunión si existe (cascada ORM/DB borra
       Hablante y AsignacionDeHablante automáticamente vía ondelete=CASCADE).
    2. Borra los blobs de audio/video de la GrabacionDeSesion en el almacén.
    3. Borra la Reunion — cascada en BD borra estado_historial,
       grabaciones_de_sesion, transcripciones (→ turnos_de_habla) y
       notificaciones_de_grabacion.

    Retorna False si la Reunion no existe; el llamador decide cómo mapear
    eso a una respuesta HTTP (404).
    """
    reunion = await session.get(Reunion, reunion_id)
    if reunion is None:
        return False

    # DELETE de bajo nivel (no session.delete()): Diarizacion.hablantes es una
    # relationship ORM bidireccional sin cascade configurado, así que
    # session.delete() intentaría poner NULL en hablantes.diarizacion_id
    # (columna NOT NULL) antes de borrar, en vez de dejar que la FK
    # ondelete=CASCADE de la base de datos borre hablantes/asignaciones.
    await session.execute(delete(Diarizacion).where(Diarizacion.reunion_id == reunion_id))
    await session.flush()

    stmt_grabacion = select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
    grabacion = (await session.execute(stmt_grabacion)).scalar_one_or_none()
    if grabacion is not None:
        with contextlib.suppress(Exception):
            await almacen.eliminar(grabacion.audio_ref)
        if grabacion.video_ref is not None:
            with contextlib.suppress(Exception):
                await almacen.eliminar(grabacion.video_ref)

    await session.delete(reunion)
    await session.flush()
    return True


async def solicitar_union(
    session: AsyncSession,
    reunion_id: str,
    cola: ColaDeTrabajos,
) -> ResultadoTransicion:
    """Solicita la unión manual a una Reunion en cola (Req. 1.2).

    1. Carga la Reunion por ID.
    2. Aplica evento "iniciar_captura" vía registrar_transicion.
    3. Si exitosa, publica trabajo en la cola (tema="union", mensaje={reunion_id, enlace_meet}).
    4. Retorna el resultado de la transición.
    """
    reunion = await session.get(Reunion, reunion_id)
    if reunion is None:
        return ResultadoTransicion(exitosa=False, nuevo_estado="en_cola")

    resultado = await registrar_transicion(session, reunion, "iniciar_captura")

    if resultado.exitosa:
        await cola.publicar(
            tema="union",
            mensaje={"reunion_id": reunion.id, "enlace_meet": reunion.enlace_meet},
        )

    return resultado


async def programar_union_por_calendario(
    session: AsyncSession,
    reunion_id: str,
    cola: ColaDeTrabajos,
) -> ResultadoTransicion:
    """Dispara la unión cuando llega la hora_inicio_programada (Req. 1.3).

    Mismo flujo que solicitar_union pero diseñado para ser invocado por un
    scheduler cuando llega la hora programada. Aplica evento "iniciar_captura".
    """
    reunion = await session.get(Reunion, reunion_id)
    if reunion is None:
        return ResultadoTransicion(exitosa=False, nuevo_estado="en_cola")

    resultado = await registrar_transicion(session, reunion, "iniciar_captura")

    if resultado.exitosa:
        await cola.publicar(
            tema="union",
            mensaje={"reunion_id": reunion.id, "enlace_meet": reunion.enlace_meet},
        )

    return resultado
