"""Máquina de estados del Estado_De_Proceso — función pura de transición.

Este módulo implementa `aplicar_evento` como función pura (sin acceso a DB ni efectos
secundarios). Define las transiciones válidas del diagrama de estados del diseño y
computa el siguiente estado dado un estado actual y un evento de dominio.

Requirements: 1.4, 1.5, 2.5, 3.6, 4.1, 4.2, 4.4
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constantes del dominio
# ---------------------------------------------------------------------------

ESTADOS: set[str] = {
    "en_cola",
    "uniendose",
    "grabando",
    "transcribiendo",
    "completado",
    "fallido",
}

ESTADOS_TERMINALES: set[str] = {"completado", "fallido"}

CAUSAS_FALLO_VALIDAS: set[str] = {
    "no_pudo_unirse",
    "reunion_cancelada",
    "fallo_del_motor",
}

# Mapa de transiciones: estado_actual → {evento → nuevo_estado}
TRANSICIONES_VALIDAS: dict[str, dict[str, str]] = {
    "en_cola": {
        "iniciar_captura": "uniendose",
        "reunion_cancelada": "fallido",
    },
    "uniendose": {
        "captura_iniciada": "grabando",
        "timeout_union": "fallido",
    },
    "grabando": {
        "grabacion_subida": "transcribiendo",
    },
    "transcribiendo": {
        "transcripcion_completada": "completado",
        "fallo_motor": "fallido",
    },
}

# Mapa de eventos que conducen a "fallido" → causa_fallo correspondiente
EVENTO_A_CAUSA: dict[str, str] = {
    "reunion_cancelada": "reunion_cancelada",
    "timeout_union": "no_pudo_unirse",
    "fallo_motor": "fallo_del_motor",
}


# ---------------------------------------------------------------------------
# Resultado de la transición
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultadoTransicion:
    """Resultado de aplicar un evento a un estado.

    Attributes:
        exitosa: True si la transición fue válida y se aplicó.
        nuevo_estado: Estado resultante (igual al actual si exitosa=False).
        causa_fallo: Causa de fallo si la transición lleva a 'fallido', None en otro caso.
    """

    exitosa: bool
    nuevo_estado: str
    causa_fallo: str | None = None


# ---------------------------------------------------------------------------
# Función pura de transición
# ---------------------------------------------------------------------------


def aplicar_evento(estado_actual: str, evento: str) -> ResultadoTransicion:
    """Aplica un evento al estado actual y retorna el resultado de la transición.

    Reglas:
    - Si `estado_actual` es terminal (completado/fallido): retorna exitosa=False.
    - Si `evento` no es válido para `estado_actual`: retorna exitosa=False.
    - Si la transición lleva a 'fallido': incluye la causa_fallo correspondiente.
    - En otro caso: retorna el nuevo estado con exitosa=True.

    Esta función es PURA: no accede a base de datos ni produce efectos secundarios.
    Solo computa el siguiente estado.
    """
    # Estados terminales: inmutables
    if estado_actual in ESTADOS_TERMINALES:
        return ResultadoTransicion(exitosa=False, nuevo_estado=estado_actual)

    # Buscar transiciones válidas desde el estado actual
    transiciones_desde_estado = TRANSICIONES_VALIDAS.get(estado_actual)
    if transiciones_desde_estado is None:
        return ResultadoTransicion(exitosa=False, nuevo_estado=estado_actual)

    # Buscar si el evento está en las transiciones válidas
    nuevo_estado = transiciones_desde_estado.get(evento)
    if nuevo_estado is None:
        return ResultadoTransicion(exitosa=False, nuevo_estado=estado_actual)

    # Transición válida — determinar causa_fallo si aplica
    causa_fallo: str | None = None
    if nuevo_estado == "fallido":
        causa_fallo = EVENTO_A_CAUSA.get(evento)

    return ResultadoTransicion(
        exitosa=True,
        nuevo_estado=nuevo_estado,
        causa_fallo=causa_fallo,
    )
