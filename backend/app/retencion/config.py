"""Configuración del periodo de retención de datos (Req. 6.2, 6.6)."""

import os
from datetime import timedelta

_DEFAULT_RETENTION_DAYS = 90


def obtener_periodo_retencion() -> timedelta:
    """Lee el periodo de retención desde la variable de entorno RETENTION_DAYS.

    Si no está definida o no es un entero válido, usa el valor por defecto (90 días).
    """
    raw = os.environ.get("RETENTION_DAYS", "")
    try:
        days = int(raw)
    except (ValueError, TypeError):
        days = _DEFAULT_RETENTION_DAYS
    return timedelta(days=days)
