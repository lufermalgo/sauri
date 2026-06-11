"""Contrato de ingesta — esquema Pydantic que cualquier Asistente_De_Reunion debe cumplir.

El campo `origen_captura` registra la fuente (extensión Chrome o bot servidor)
pero NO altera el pipeline posterior (almacenar → transcribir → persistir).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DatosIngesta(BaseModel):
    """Datos que acompañan la subida de una Grabacion_De_Sesion al backend.

    Este es el contrato común que CUALQUIER implementación del Asistente_De_Reunion
    (extensión de Chrome o bot servidor) debe proveer junto con los archivos binarios.

    El campo `origen_captura` se almacena para trazabilidad, pero el pipeline
    de ingesta → transcripción → persistencia se comporta idénticamente
    independientemente de su valor (Req. 2.1, 2.2).
    """

    reunion_id: str = Field(
        ...,
        description="Identificador de la Reunion a la que pertenece la grabación.",
    )
    clave_idempotencia: str = Field(
        ...,
        description=(
            "Clave estable por sessionId/Reunion que permite reintentos "
            "de subida seguros sin duplicar la Grabacion_De_Sesion."
        ),
    )
    origen_captura: Literal["extension_chrome", "bot_servidor"] = Field(
        ...,
        description=(
            "Fuente que produjo la grabación. No altera el comportamiento "
            "del pipeline posterior."
        ),
    )
    duracion_segundos: int = Field(
        ...,
        ge=0,
        description="Duración en segundos de la grabación capturada.",
    )
    interrumpida: bool = Field(
        default=False,
        description="True si la captura se interrumpió antes del fin de la reunión (Req. 2.4).",
    )
    notificacion_emitida_en: str | None = Field(
        default=None,
        description=(
            "Marca ISO-8601 de emisión de la Notificacion_De_Grabacion. "
            "Si se provee, el backend registra el evento auditable (Req. 6.5)."
        ),
    )
