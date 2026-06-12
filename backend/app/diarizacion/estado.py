"""Máquina de estados del Estado_De_Diarizacion — función pura de transición.

Este módulo implementa `aplicar_evento_diarizacion` como función pura (sin acceso a DB
ni efectos secundarios). Define las transiciones válidas del ciclo de vida propio de la
Diarizacion y computa el siguiente estado dado un estado actual y un evento de dominio.

Esta máquina es INDEPENDIENTE de la de Reunion; no invoca `registrar_transicion` ni
escribe en `reuniones` ni en `estado_historial`.

Requirements: 9.1, 9.2, 9.3
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constantes del dominio
# ---------------------------------------------------------------------------

ESTADOS: set[str] = {
    "pendiente",
    "en_proceso",
    "completada",
    "fallida",
}

ESTADOS_TERMINALES: set[str] = {"completada", "fallida"}

CAUSAS_FALLO_VALIDAS: set[str] = {
    "fallo_del_motor",
}

# Mapa de transiciones: estado_actual → {evento → nuevo_estado}
TRANSICIONES_VALIDAS: dict[str, dict[str, str]] = {
    "pendiente": {
        "iniciar_proceso": "en_proceso",
    },
    "en_proceso": {
        "diarizacion_completada": "completada",
        "fallo_motor": "fallida",
    },
}

# Mapa de eventos que conducen a "fallida" → causa_fallo correspondiente
EVENTO_A_CAUSA: dict[str, str] = {
    "fallo_motor": "fallo_del_motor",
}


# ---------------------------------------------------------------------------
# Resultado de la transición
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultadoTransicionDiarizacion:
    """Resultado de aplicar un evento a un estado de diarización.

    Attributes:
        exitosa: True si la transición fue válida y se aplicó.
        nuevo_estado: Estado resultante (igual al actual si exitosa=False).
        causa_fallo: Causa de fallo si la transición lleva a 'fallida', None en otro caso.
    """

    exitosa: bool
    nuevo_estado: str
    causa_fallo: str | None = None


# ---------------------------------------------------------------------------
# Función pura de transición
# ---------------------------------------------------------------------------


def aplicar_evento_diarizacion(
    estado_actual: str, evento: str
) -> ResultadoTransicionDiarizacion:
    """Aplica un evento al estado actual y retorna el resultado de la transición.

    Reglas:
    - Si `estado_actual` es terminal (completada/fallida): retorna exitosa=False.
    - Si `evento` no es válido para `estado_actual`: retorna exitosa=False.
    - Si la transición lleva a 'fallida': incluye la causa_fallo correspondiente.
    - En otro caso: retorna el nuevo estado con exitosa=True.

    Esta función es PURA: no accede a base de datos ni produce efectos secundarios.
    Solo computa el siguiente estado.
    """
    # Estados terminales: inmutables
    if estado_actual in ESTADOS_TERMINALES:
        return ResultadoTransicionDiarizacion(
            exitosa=False, nuevo_estado=estado_actual
        )

    # Buscar transiciones válidas desde el estado actual
    transiciones_desde_estado = TRANSICIONES_VALIDAS.get(estado_actual)
    if transiciones_desde_estado is None:
        return ResultadoTransicionDiarizacion(
            exitosa=False, nuevo_estado=estado_actual
        )

    # Buscar si el evento está en las transiciones válidas
    nuevo_estado = transiciones_desde_estado.get(evento)
    if nuevo_estado is None:
        return ResultadoTransicionDiarizacion(
            exitosa=False, nuevo_estado=estado_actual
        )

    # Transición válida — determinar causa_fallo si aplica
    causa_fallo: str | None = None
    if nuevo_estado == "fallida":
        causa_fallo = EVENTO_A_CAUSA.get(evento)

    return ResultadoTransicionDiarizacion(
        exitosa=True,
        nuevo_estado=nuevo_estado,
        causa_fallo=causa_fallo,
    )
