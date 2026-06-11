"""Schemas Pydantic para validación de entrada de reuniones.

Define los tres tipos de entrada aceptados para registrar una Reunion:
- EntradaReunionEnlace: solo enlace de Google Meet.
- EntradaReunionCalendario: enlace + id de invitación de calendario + hora de inicio.
- EntradaReunionManual: solicitud manual con enlace de Google Meet.

Requirements: 1.1, 1.7
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Union

from pydantic import BaseModel, field_validator

# Patrón para enlaces válidos de Google Meet
_MEET_PATTERN = re.compile(r"^https://meet\.google\.com/.+")


def _validar_enlace_meet(enlace: str) -> str:
    """Valida que el enlace comience con https://meet.google.com/."""
    if not _MEET_PATTERN.match(enlace):
        raise ValueError(
            "El enlace debe comenzar con 'https://meet.google.com/'"
        )
    return enlace


class EntradaReunionEnlace(BaseModel):
    """Entrada de reunión por enlace directo de Google Meet."""

    enlace_meet: str

    @field_validator("enlace_meet")
    @classmethod
    def validar_enlace(cls, v: str) -> str:
        return _validar_enlace_meet(v)


class EntradaReunionCalendario(BaseModel):
    """Entrada de reunión por invitación de calendario con enlace de Meet."""

    enlace_meet: str
    id_invitacion_calendario: str
    hora_inicio_programada: datetime

    @field_validator("enlace_meet")
    @classmethod
    def validar_enlace(cls, v: str) -> str:
        return _validar_enlace_meet(v)


class EntradaReunionManual(BaseModel):
    """Entrada de reunión por solicitud manual con enlace de Google Meet."""

    enlace_meet: str

    @field_validator("enlace_meet")
    @classmethod
    def validar_enlace(cls, v: str) -> str:
        return _validar_enlace_meet(v)


# Union type — acepta cualquiera de los tres tipos de entrada
EntradaReunion = Union[EntradaReunionCalendario, EntradaReunionEnlace, EntradaReunionManual]
