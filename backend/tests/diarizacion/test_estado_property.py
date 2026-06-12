"""Prueba de propiedad para la máquina de estados del Estado_De_Diarizacion.

# Feature: identificacion-hablantes, Property 16: Corrección de la máquina de estados del Estado_De_Diarizacion
Validates: Requirements 9.1, 9.2, 9.3
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarizacion.estado import aplicar_evento_diarizacion

# ---------------------------------------------------------------------------
# Dominio de la máquina de estados
# ---------------------------------------------------------------------------

ESTADOS = ["pendiente", "en_proceso", "completada", "fallida"]
ESTADOS_TERMINALES = {"completada", "fallida"}
EVENTOS = ["iniciar_proceso", "diarizacion_completada", "fallo_motor"]

# Transiciones válidas: (estado_actual, evento) → (nuevo_estado, causa_fallo)
TRANSICIONES_VALIDAS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("pendiente", "iniciar_proceso"): ("en_proceso", None),
    ("en_proceso", "diarizacion_completada"): ("completada", None),
    ("en_proceso", "fallo_motor"): ("fallida", "fallo_del_motor"),
}


# ---------------------------------------------------------------------------
# Property 16: Corrección de la máquina de estados del Estado_De_Diarizacion
# Feature: identificacion-hablantes, Property 16: Corrección de la máquina de estados del Estado_De_Diarizacion
# Validates: Requirements 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    estado_actual=st.sampled_from(ESTADOS),
    evento=st.sampled_from(EVENTOS),
)
def test_property_16_transiciones_validas_producen_estado_correcto(
    estado_actual: str, evento: str
) -> None:
    """Transiciones válidas producen el estado esperado con exitosa=True."""
    resultado = aplicar_evento_diarizacion(estado_actual, evento)
    par = (estado_actual, evento)

    if par in TRANSICIONES_VALIDAS:
        nuevo_estado_esperado, causa_esperada = TRANSICIONES_VALIDAS[par]
        assert resultado.exitosa is True, (
            f"Transición ({estado_actual}, {evento}) debería ser exitosa"
        )
        assert resultado.nuevo_estado == nuevo_estado_esperado, (
            f"Esperado {nuevo_estado_esperado}, obtenido {resultado.nuevo_estado}"
        )
        assert resultado.causa_fallo == causa_esperada, (
            f"Esperada causa {causa_esperada}, obtenida {resultado.causa_fallo}"
        )
    else:
        # Transición inválida o estado terminal: preserva estado, exitosa=False
        assert resultado.exitosa is False, (
            f"Par ({estado_actual}, {evento}) NO debería ser exitosa"
        )
        assert resultado.nuevo_estado == estado_actual, (
            f"Estado debería preservarse como {estado_actual}, "
            f"obtenido {resultado.nuevo_estado}"
        )


@settings(max_examples=100)
@given(
    estado_terminal=st.sampled_from(list(ESTADOS_TERMINALES)),
    evento=st.sampled_from(EVENTOS),
)
def test_property_16_estados_terminales_son_inmutables(
    estado_terminal: str, evento: str
) -> None:
    """Estados terminales (completada, fallida) rechazan cualquier evento."""
    resultado = aplicar_evento_diarizacion(estado_terminal, evento)

    assert resultado.exitosa is False, (
        f"Estado terminal {estado_terminal} no debería aceptar evento {evento}"
    )
    assert resultado.nuevo_estado == estado_terminal, (
        f"Estado terminal debe preservarse: esperado {estado_terminal}, "
        f"obtenido {resultado.nuevo_estado}"
    )


@settings(max_examples=100)
@given(
    estado_actual=st.sampled_from(ESTADOS),
    evento_invalido=st.text(
        alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
        min_size=1,
        max_size=30,
    ).filter(lambda e: e not in EVENTOS),
)
def test_property_16_eventos_no_reconocidos_rechazan_transicion(
    estado_actual: str, evento_invalido: str
) -> None:
    """Eventos no reconocidos siempre retornan exitosa=False preservando el estado."""
    resultado = aplicar_evento_diarizacion(estado_actual, evento_invalido)

    assert resultado.exitosa is False, (
        f"Evento no reconocido '{evento_invalido}' no debería ser exitoso "
        f"en estado {estado_actual}"
    )
    assert resultado.nuevo_estado == estado_actual, (
        f"Estado debería preservarse como {estado_actual}, "
        f"obtenido {resultado.nuevo_estado}"
    )
