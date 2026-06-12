"""Etiquetador_De_Hablantes — función pura de etiquetado anónimo.

Agrupa SegmentosDeHablante por Etiqueta_De_Hablante_Cruda, ordena por primera
aparición con desempate lexicográfico, y asigna etiquetas anónimas consecutivas.

Requirements: 5.5, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

from dataclasses import dataclass

from app.diarizacion.motor_diarizacion import SegmentoDeHablante


@dataclass(frozen=True, slots=True)
class Hablante:
    """Hablante anónimo identificado por el etiquetador.

    No contiene ningún campo de identidad nominal ni dato personal (Req. 6.3).

    Attributes:
        etiqueta_cruda: Etiqueta_De_Hablante_Cruda original del motor.
        etiqueta: Etiqueta_De_Hablante con formato "Hablante N" (Req. 6.2).
        orden: Consecutivo desde 1, por primera aparición (Req. 6.2).
    """

    etiqueta_cruda: str
    etiqueta: str
    orden: int


def etiquetar_hablantes(segmentos: list[SegmentoDeHablante]) -> list[Hablante]:
    """Etiqueta hablantes de forma anónima, ordenada y determinista.

    Algoritmo:
    1. Agrupar segmentos por etiqueta_cruda; calcular el primer inicio_ms
       de cada etiqueta cruda (Req. 6.1).
    2. Ordenar por (primer_inicio_ms, etiqueta_cruda) ascendente — desempate
       lexicográfico determinista (Req. 6.4).
    3. Asignar orden consecutivo desde 1 y etiqueta "Hablante N" (Req. 6.2).
    4. Sin campos de identidad nominal (Req. 6.3).

    Args:
        segmentos: Lista de SegmentoDeHablante producidos por el motor.

    Returns:
        Lista de Hablante, uno por cada etiqueta cruda distinta,
        ordenados por primera aparición temporal.
    """
    if not segmentos:
        return []

    # Paso 1: Calcular primer inicio_ms por etiqueta cruda
    primer_inicio: dict[str, int] = {}
    for seg in segmentos:
        if seg.etiqueta_cruda not in primer_inicio:
            primer_inicio[seg.etiqueta_cruda] = seg.inicio_ms
        else:
            primer_inicio[seg.etiqueta_cruda] = min(
                primer_inicio[seg.etiqueta_cruda], seg.inicio_ms
            )

    # Paso 2: Ordenar por (primer_inicio_ms, etiqueta_cruda) ascendente
    etiquetas_ordenadas = sorted(
        primer_inicio.keys(),
        key=lambda ec: (primer_inicio[ec], ec),
    )

    # Paso 3: Asignar orden consecutivo y etiqueta "Hablante N"
    hablantes: list[Hablante] = []
    for i, etiqueta_cruda in enumerate(etiquetas_ordenadas, start=1):
        hablantes.append(
            Hablante(
                etiqueta_cruda=etiqueta_cruda,
                etiqueta=f"Hablante {i}",
                orden=i,
            )
        )

    return hablantes
