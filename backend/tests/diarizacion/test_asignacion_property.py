"""Prueba de propiedad para la asignación de turnos por máximo solape temporal.

# Feature: identificacion-hablantes, Property 9: Asignación de Turnos por máximo solape con desempate determinista
Validates: Requirements 7.1, 7.2
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.diarizacion.asignacion import asignar_turnos
from app.diarizacion.etiquetado import Hablante
from app.diarizacion.motor_diarizacion import SegmentoDeHablante


# ---------------------------------------------------------------------------
# Tipos auxiliares para los turnos (simplificación del ORM TurnoDeHabla)
# ---------------------------------------------------------------------------


@dataclass
class Turno:
    """Representación simplificada de un Turno_De_Habla para pruebas."""

    id: str
    inicio_ms: int
    fin_ms: int
    orden: int


# ---------------------------------------------------------------------------
# Estrategias de generación
# ---------------------------------------------------------------------------

# Etiquetas crudas posibles para los hablantes
etiquetas_crudas_strategy = st.sampled_from(
    ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03", "SPEAKER_04"]
)


def _segmento_strategy(
    etiqueta: st.SearchStrategy[str] = etiquetas_crudas_strategy,
) -> st.SearchStrategy[SegmentoDeHablante]:
    """Genera un SegmentoDeHablante válido."""
    return st.builds(
        SegmentoDeHablante,
        etiqueta_cruda=etiqueta,
        inicio_ms=st.integers(min_value=0, max_value=100_000),
        fin_ms=st.integers(min_value=0, max_value=100_000),
    ).filter(lambda s: s.fin_ms >= s.inicio_ms)


segmentos_strategy = st.lists(
    _segmento_strategy(), min_size=1, max_size=20
)

turnos_strategy = st.lists(
    st.builds(
        Turno,
        id=st.uuids().map(str),
        inicio_ms=st.integers(min_value=0, max_value=100_000),
        fin_ms=st.integers(min_value=0, max_value=100_000),
        orden=st.integers(min_value=1, max_value=100),
    ).filter(lambda t: t.fin_ms >= t.inicio_ms),
    min_size=1,
    max_size=10,
)


def _crear_hablantes(segmentos: list[SegmentoDeHablante]) -> list[Hablante]:
    """Crea una lista de Hablante a partir de las etiquetas crudas distintas.

    Asigna orden consecutivo desde 1 (por orden de primera aparición).
    """
    etiquetas_vistas: dict[str, int] = {}
    for seg in segmentos:
        if seg.etiqueta_cruda not in etiquetas_vistas:
            etiquetas_vistas[seg.etiqueta_cruda] = len(etiquetas_vistas) + 1

    return [
        Hablante(
            etiqueta_cruda=etiqueta,
            etiqueta=f"Hablante {orden}",
            orden=orden,
        )
        for etiqueta, orden in etiquetas_vistas.items()
    ]


def _calcular_solape(turno: Turno, segmento: SegmentoDeHablante) -> int:
    """Calcula el solape temporal entre un turno y un segmento.

    Fórmula: max(0, min(turno.fin_ms, seg.fin_ms) - max(turno.inicio_ms, seg.inicio_ms))
    """
    return max(0, min(turno.fin_ms, segmento.fin_ms) - max(turno.inicio_ms, segmento.inicio_ms))


# ---------------------------------------------------------------------------
# Property 9: Asignación de Turnos por máximo solape con desempate determinista
# Feature: identificacion-hablantes, Property 9: Asignación de Turnos por máximo solape con desempate determinista
# Validates: Requirements 7.1, 7.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    turnos=turnos_strategy,
    segmentos=segmentos_strategy,
)
def test_property_9_exactamente_una_asignacion_por_turno(
    turnos: list[Turno],
    segmentos: list[SegmentoDeHablante],
) -> None:
    """El asignador produce exactamente una asignación por turno."""
    hablantes = _crear_hablantes(segmentos)
    assume(len(hablantes) >= 1)

    resultado = asignar_turnos(turnos, segmentos, hablantes)

    assert len(resultado) == len(turnos), (
        f"Se esperaban {len(turnos)} asignaciones, se obtuvieron {len(resultado)}"
    )
    # Cada elemento es una tupla (turno_id, hablante)
    for turno_id, hablante in resultado:
        assert isinstance(turno_id, str)
        assert isinstance(hablante, Hablante)


@settings(max_examples=100)
@given(
    turnos=turnos_strategy,
    segmentos=segmentos_strategy,
)
def test_property_9_asignacion_al_hablante_de_maximo_solape(
    turnos: list[Turno],
    segmentos: list[SegmentoDeHablante],
) -> None:
    """Cada turno se asigna al hablante con máximo solape acumulado."""
    hablantes = _crear_hablantes(segmentos)
    assume(len(hablantes) >= 1)

    resultado = asignar_turnos(turnos, segmentos, hablantes)

    for turno, (turno_id, hablante_asignado) in zip(turnos, resultado):
        assert turno_id == turno.id

        # Calcular solape acumulado por hablante
        solapes: dict[str, int] = {}
        for h in hablantes:
            solape_acumulado = sum(
                _calcular_solape(turno, seg)
                for seg in segmentos
                if seg.etiqueta_cruda == h.etiqueta_cruda
            )
            solapes[h.etiqueta_cruda] = solape_acumulado

        # Encontrar el máximo solape
        max_solape = max(solapes.values())

        # El hablante asignado debe tener el máximo solape
        assert solapes[hablante_asignado.etiqueta_cruda] == max_solape, (
            f"Turno {turno.id}: hablante asignado '{hablante_asignado.etiqueta_cruda}' "
            f"tiene solape {solapes[hablante_asignado.etiqueta_cruda]} pero el máximo es {max_solape}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
@given(
    turnos=turnos_strategy,
    segmentos=segmentos_strategy,
)
def test_property_9_desempate_por_menor_orden(
    turnos: list[Turno],
    segmentos: list[SegmentoDeHablante],
) -> None:
    """En caso de empate de solape, se asigna al hablante de menor orden."""
    hablantes = _crear_hablantes(segmentos)
    assume(len(hablantes) >= 2)

    resultado = asignar_turnos(turnos, segmentos, hablantes)

    for turno, (turno_id, hablante_asignado) in zip(turnos, resultado):
        # Calcular solape acumulado por hablante
        solapes: dict[str, int] = {}
        for h in hablantes:
            solape_acumulado = sum(
                _calcular_solape(turno, seg)
                for seg in segmentos
                if seg.etiqueta_cruda == h.etiqueta_cruda
            )
            solapes[h.etiqueta_cruda] = solape_acumulado

        max_solape = max(solapes.values())

        # Candidatos con el mismo máximo solape
        candidatos = [
            h for h in hablantes
            if solapes[h.etiqueta_cruda] == max_solape
        ]

        if len(candidatos) > 1:
            # En empate, debe ganar el de menor orden
            menor_orden = min(c.orden for c in candidatos)
            assert hablante_asignado.orden == menor_orden, (
                f"Turno {turno.id}: empate de solape ({max_solape}ms) entre "
                f"{[c.etiqueta for c in candidatos]}, esperado orden {menor_orden} "
                f"pero se asignó orden {hablante_asignado.orden}"
            )


# ---------------------------------------------------------------------------
# Property 10: Preservación de los Turnos_De_Habla de la Transcripcion
# Feature: identificacion-hablantes, Property 10: Preservación de los Turnos_De_Habla de la Transcripcion
# Validates: Requirements 7.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    turnos=turnos_strategy,
    segmentos=segmentos_strategy,
)
def test_property_10_preservacion_de_turnos_de_habla(
    turnos: list[Turno],
    segmentos: list[SegmentoDeHablante],
) -> None:
    """asignar_turnos no modifica texto, inicio_ms, fin_ms ni orden de los turnos."""
    hablantes = _crear_hablantes(segmentos)
    assume(len(hablantes) >= 1)

    # Capturar estado original de los turnos
    turnos_antes = [
        (t.id, t.inicio_ms, t.fin_ms, t.orden) for t in turnos
    ]

    asignar_turnos(turnos, segmentos, hablantes)

    # Verificar que los turnos no fueron modificados (Req. 7.3)
    turnos_despues = [
        (t.id, t.inicio_ms, t.fin_ms, t.orden) for t in turnos
    ]
    assert turnos_antes == turnos_despues, (
        "asignar_turnos modificó los turnos de entrada"
    )
