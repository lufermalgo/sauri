"""Tests de propiedad para etiquetado.py.

# Feature: identificacion-hablantes, Property 7: Número de hablantes igual a etiquetas crudas distintas
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarizacion.motor_diarizacion import SegmentoDeHablante
from app.diarizacion.etiquetado import etiquetar_hablantes


# ---------------------------------------------------------------------------
# Estrategia: generar listas de SegmentoDeHablante con etiquetas crudas variadas
# ---------------------------------------------------------------------------

etiqueta_cruda_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=20,
)

segmento_strategy = st.builds(
    SegmentoDeHablante,
    etiqueta_cruda=etiqueta_cruda_strategy,
    inicio_ms=st.integers(min_value=0, max_value=10_000_000),
    fin_ms=st.integers(min_value=0, max_value=10_000_000),
).filter(lambda s: s.fin_ms >= s.inicio_ms)


lista_segmentos_strategy = st.lists(segmento_strategy, min_size=1, max_size=30)


# ---------------------------------------------------------------------------
# Property 7: Número de hablantes igual a etiquetas crudas distintas
# Feature: identificacion-hablantes, Property 7: Número de hablantes igual a etiquetas crudas distintas
# Validates: Requirements 5.5, 6.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segmentos=lista_segmentos_strategy)
def test_property_7_numero_hablantes_igual_etiquetas_crudas_distintas(
    segmentos: list[SegmentoDeHablante],
) -> None:
    """etiquetar_hablantes crea exactamente un Hablante por cada etiqueta cruda distinta (biyección)."""
    resultado = etiquetar_hablantes(segmentos)

    etiquetas_crudas_distintas = set(s.etiqueta_cruda for s in segmentos)
    num_esperado = len(etiquetas_crudas_distintas)

    # Verificar que len(result) == número de etiquetas crudas distintas
    assert len(resultado) == num_esperado, (
        f"Se esperaban {num_esperado} Hablantes (uno por etiqueta cruda distinta), "
        f"pero se obtuvieron {len(resultado)}"
    )

    # Verificar biyección: cada etiqueta cruda distinta tiene exactamente un Hablante
    etiquetas_crudas_en_resultado = set(h.etiqueta_cruda for h in resultado)
    assert etiquetas_crudas_en_resultado == etiquetas_crudas_distintas, (
        f"Las etiquetas crudas en el resultado {etiquetas_crudas_en_resultado} "
        f"no coinciden con las etiquetas crudas distintas de los segmentos {etiquetas_crudas_distintas}"
    )

    # Verificar que no hay Hablantes duplicados por etiqueta cruda (inyectividad)
    assert len(etiquetas_crudas_en_resultado) == len(resultado), (
        f"Hay Hablantes duplicados: {len(resultado)} hablantes pero solo "
        f"{len(etiquetas_crudas_en_resultado)} etiquetas crudas distintas en el resultado"
    )


# ---------------------------------------------------------------------------
# Property 8: Etiquetado anónimo, ordenado y determinista de hablantes
# Feature: identificacion-hablantes, Property 8: Etiquetado anónimo, ordenado y determinista de hablantes
# Validates: Requirements 6.2, 6.3, 6.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(segmentos=lista_segmentos_strategy)
def test_property_8_etiquetado_anonimo_ordenado_y_determinista(
    segmentos: list[SegmentoDeHablante],
) -> None:
    """etiquetar_hablantes ordena por primer inicio_ms con desempate lexicográfico,
    asigna orden consecutivo desde 1, etiqueta 'Hablante N', sin campos nominales."""
    resultado = etiquetar_hablantes(segmentos)

    if not resultado:
        return

    # Calcular primer inicio_ms por etiqueta cruda (referencia)
    primer_inicio: dict[str, int] = {}
    for seg in segmentos:
        if seg.etiqueta_cruda not in primer_inicio:
            primer_inicio[seg.etiqueta_cruda] = seg.inicio_ms
        else:
            primer_inicio[seg.etiqueta_cruda] = min(
                primer_inicio[seg.etiqueta_cruda], seg.inicio_ms
            )

    # Verificar orden: por (primer_inicio_ms, etiqueta_cruda) ascendente (Req. 6.4)
    claves_resultado = [
        (primer_inicio[h.etiqueta_cruda], h.etiqueta_cruda) for h in resultado
    ]
    assert claves_resultado == sorted(claves_resultado), (
        f"Los hablantes no están ordenados por (primer_inicio_ms, etiqueta_cruda): "
        f"{claves_resultado}"
    )

    # Verificar orden consecutivo desde 1 (Req. 6.2)
    ordenes = [h.orden for h in resultado]
    assert ordenes == list(range(1, len(resultado) + 1)), (
        f"Los órdenes no son consecutivos desde 1: {ordenes}"
    )

    # Verificar etiqueta = "Hablante N" (Req. 6.2)
    for h in resultado:
        assert h.etiqueta == f"Hablante {h.orden}", (
            f"Etiqueta incorrecta: esperada 'Hablante {h.orden}', obtenida '{h.etiqueta}'"
        )

    # Verificar sin campos de identidad nominal (Req. 6.3)
    # Solo tiene etiqueta_cruda, etiqueta y orden — sin nombre, email, etc.
    campos = set(resultado[0].__dataclass_fields__.keys())
    assert campos == {"etiqueta_cruda", "etiqueta", "orden"}, (
        f"Hablante tiene campos inesperados de identidad nominal: {campos}"
    )
