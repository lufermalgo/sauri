"""Cálculo de expiración para Grabacion_De_Sesion y Transcripcion (Req. 6.2, 6.6)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.infra.models import GrabacionDeSesion, Transcripcion


def calcular_expiracion(creada_en: datetime, periodo: timedelta) -> datetime:
    """Calcula la fecha de expiración: creada_en + periodo.

    Requirements 6.2, 6.6: la fecha de expiración para
    Grabacion_De_Sesion y Transcripcion es exactamente creada_en + periodo.
    """
    return creada_en + periodo


def aplicar_retencion(
    grabacion: GrabacionDeSesion | None,
    transcripcion: Transcripcion | None,
    periodo: timedelta,
) -> None:
    """Sets expira_en on both entities based on their creation timestamps.

    Para GrabacionDeSesion se usa finalizada_en como referencia temporal.
    Para Transcripcion se usa creada_en.
    """
    if grabacion:
        grabacion.expira_en = calcular_expiracion(grabacion.finalizada_en, periodo)
    if transcripcion:
        transcripcion.expira_en = calcular_expiracion(transcripcion.creada_en, periodo)
