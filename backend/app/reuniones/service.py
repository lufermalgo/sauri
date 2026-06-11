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

import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import EstadoHistorial, Reunion
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
        ocurrido_en=datetime.now(timezone.utc),
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

    ahora = datetime.now(timezone.utc)
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
        "estado_proceso": reunion.estado_proceso,
    }

    if reunion.estado_proceso == "fallido":
        resultado["causa_fallo"] = reunion.causa_fallo

    return resultado


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
