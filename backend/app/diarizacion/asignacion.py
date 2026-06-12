"""Asignador_De_Turnos — función pura de asignación por máximo solape temporal.

Asigna cada Turno_De_Habla al Hablante cuyo Solape_Temporal acumulado es máximo,
con desempate determinista por menor orden.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from typing import Any

from app.diarizacion.etiquetado import Hablante
from app.diarizacion.motor_diarizacion import SegmentoDeHablante


def asignar_turnos(
    turnos: list[Any],
    segmentos: list[SegmentoDeHablante],
    hablantes: list[Hablante],
) -> list[tuple[str, Hablante]]:
    """Asigna cada turno al hablante de máximo solape temporal acumulado.

    Algoritmo (Req. 7.1, 7.2):
    Para cada turno [ts, te]:
    1. Para cada hablante, sumar el solape con todos sus segmentos.
       Solape = max(0, min(te, se) - max(ts, ss))
    2. Seleccionar el hablante con solape acumulado máximo.
    3. Desempate: si hay empate (o todos tienen solape cero), asignar
       al hablante de menor orden.
    4. Producir exactamente una asignación por turno.

    Los turnos no se modifican (Req. 7.3).
    Si no hay turnos → cero asignaciones (Req. 7.4).
    Si no hay segmentos/hablantes → cero asignaciones (Req. 7.5).

    Args:
        turnos: Lista de objetos con .id, .inicio_ms, .fin_ms.
        segmentos: Lista de SegmentoDeHablante del motor.
        hablantes: Lista de Hablante del etiquetador.

    Returns:
        Lista de tuplas (turno_id, hablante_asignado), una por turno.
    """
    if not turnos or not hablantes:
        return []

    # Pre-agrupar segmentos por etiqueta cruda para eficiencia
    segmentos_por_etiqueta: dict[str, list[SegmentoDeHablante]] = {}
    for seg in segmentos:
        segmentos_por_etiqueta.setdefault(seg.etiqueta_cruda, []).append(seg)

    asignaciones: list[tuple[str, Hablante]] = []

    for turno in turnos:
        ts = turno.inicio_ms
        te = turno.fin_ms

        mejor_hablante: Hablante | None = None
        mejor_solape: int = -1

        for hablante in hablantes:
            segs_hablante = segmentos_por_etiqueta.get(hablante.etiqueta_cruda, [])
            solape_acumulado = sum(
                max(0, min(te, seg.fin_ms) - max(ts, seg.inicio_ms))
                for seg in segs_hablante
            )

            # Seleccionar si mayor solape, o empate con menor orden
            if (
                solape_acumulado > mejor_solape
                or (
                    solape_acumulado == mejor_solape
                    and (
                        mejor_hablante is None
                        or hablante.orden < mejor_hablante.orden
                    )
                )
            ):
                mejor_solape = solape_acumulado
                mejor_hablante = hablante

        assert mejor_hablante is not None  # Garantizado si hablantes no está vacío
        asignaciones.append((turno.id, mejor_hablante))

    return asignaciones
