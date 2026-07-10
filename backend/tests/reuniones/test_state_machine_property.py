"""Property tests de la máquina de estados pura del Estado_De_Proceso.

# Feature: meeting-capture-transcription, Property 3: Integridad de la máquina de estados
# Feature: meeting-capture-transcription, Property 4: Toda transición a "fallido" registra una causa válida
Tasks: 5.2, 5.3
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.reuniones.state_machine import (
    CAUSAS_FALLO_VALIDAS,
    ESTADOS,
    ESTADOS_TERMINALES,
    EVENTO_A_CAUSA,
    TRANSICIONES_VALIDAS,
    aplicar_evento,
)

EVENTOS = [
    "iniciar_captura",
    "reunion_cancelada",
    "captura_iniciada",
    "timeout_union",
    "grabacion_subida",
    "transcripcion_completada",
    "fallo_motor",
]


# ---------------------------------------------------------------------------
# Property 3: Integridad de la máquina de estados
# Feature: meeting-capture-transcription, Property 3: Integridad de la máquina de estados
# Validates: Requirements 1.4, 1.5, 2.5, 3.6, 4.1, 4.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(estado_actual=st.sampled_from(sorted(ESTADOS)), evento=st.sampled_from(EVENTOS))
def test_property_3_solo_transiciones_validas_producen_estado_nuevo(
    estado_actual: str, evento: str
) -> None:
    """Solo pares (estado, evento) definidos en TRANSICIONES_VALIDAS producen un nuevo estado."""
    resultado = aplicar_evento(estado_actual, evento)

    assert resultado.nuevo_estado in ESTADOS

    if estado_actual in ESTADOS_TERMINALES:
        assert resultado.exitosa is False
        assert resultado.nuevo_estado == estado_actual
        return

    transicion_esperada = TRANSICIONES_VALIDAS.get(estado_actual, {}).get(evento)
    if transicion_esperada is None:
        assert resultado.exitosa is False
        assert resultado.nuevo_estado == estado_actual
    else:
        assert resultado.exitosa is True
        assert resultado.nuevo_estado == transicion_esperada


@settings(max_examples=100)
@given(estado_terminal=st.sampled_from(sorted(ESTADOS_TERMINALES)), evento=st.sampled_from(EVENTOS))
def test_property_3_estados_terminales_son_inmutables(
    estado_terminal: str, evento: str
) -> None:
    """Estados terminales (completado, fallido) rechazan cualquier evento sin cambiar de estado."""
    resultado = aplicar_evento(estado_terminal, evento)

    assert resultado.exitosa is False
    assert resultado.nuevo_estado == estado_terminal


# ---------------------------------------------------------------------------
# Property 4: Toda transición a "fallido" registra una causa válida
# Feature: meeting-capture-transcription, Property 4: Toda transición a "fallido" registra una causa válida
# Validates: Requirements 1.6, 3.7, 4.3, 4.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(estado_actual=st.sampled_from(sorted(ESTADOS)), evento=st.sampled_from(EVENTOS))
def test_property_4_transicion_a_fallido_tiene_causa_valida(
    estado_actual: str, evento: str
) -> None:
    """Toda transición exitosa que resulta en 'fallido' registra una causa_fallo válida."""
    resultado = aplicar_evento(estado_actual, evento)

    if resultado.exitosa and resultado.nuevo_estado == "fallido":
        assert resultado.causa_fallo in CAUSAS_FALLO_VALIDAS
        assert resultado.causa_fallo == EVENTO_A_CAUSA.get(evento)
    elif resultado.exitosa:
        assert resultado.causa_fallo is None
