"""Tests de propiedad para motor_diarizacion.py.

# Feature: identificacion-hablantes, Property 6: Orden ascendente de los Segmentos_De_Hablante
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarizacion.motor_diarizacion import ResultadoDiarizacion, SegmentoDeHablante


# ---------------------------------------------------------------------------
# Estrategia: generar listas de SegmentoDeHablante con restricciones válidas
# ---------------------------------------------------------------------------

segmento_strategy = st.builds(
    SegmentoDeHablante,
    etiqueta_cruda=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=20,
    ),
    inicio_ms=st.integers(min_value=0, max_value=10_000_000),
    fin_ms=st.integers(min_value=0, max_value=10_000_000),
).filter(lambda s: s.fin_ms >= s.inicio_ms)


lista_segmentos_strategy = st.lists(segmento_strategy, min_size=0, max_size=30)


# ---------------------------------------------------------------------------
# Property 6: Orden ascendente de los Segmentos_De_Hablante
# Feature: identificacion-hablantes, Property 6: Orden ascendente de los Segmentos_De_Hablante
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segmentos=lista_segmentos_strategy)
def test_property_6_resultado_diarizacion_orden_ascendente(
    segmentos: list[SegmentoDeHablante],
) -> None:
    """Un ResultadoDiarizacion válido tiene segmentos ordenados no decreciente por inicio_ms."""
    resultado = ResultadoDiarizacion(
        segmentos=segmentos,
        num_hablantes=len(set(s.etiqueta_cruda for s in segmentos)),
    )

    for i in range(1, len(resultado.segmentos)):
        assert resultado.segmentos[i].inicio_ms >= resultado.segmentos[i - 1].inicio_ms, (
            f"Segmento en posición {i} tiene inicio_ms={resultado.segmentos[i].inicio_ms} "
            f"menor que el anterior inicio_ms={resultado.segmentos[i - 1].inicio_ms}"
        )
