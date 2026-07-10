"""Property test del cálculo del periodo de retención (expiracion.py).

# Feature: meeting-capture-transcription, Property 11: Cálculo del periodo de retención
Task: 12.2 — Validates: Requirements 6.2
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.retencion.expiracion import calcular_expiracion

fecha_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2035, 1, 1),
).map(lambda dt: dt.replace(tzinfo=UTC))

periodo_strategy = st.integers(min_value=0, max_value=3650).map(lambda dias: timedelta(days=dias))


# ---------------------------------------------------------------------------
# Property 11: Cálculo del periodo de retención
# Feature: meeting-capture-transcription, Property 11: Cálculo del periodo de retención
# Validates: Requirements 6.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(creada_en=fecha_strategy, periodo=periodo_strategy)
def test_property_11_expiracion_es_creada_en_mas_periodo(
    creada_en: datetime, periodo: timedelta
) -> None:
    """expira_en es exactamente creada_en + periodo, sin desviaciones."""
    expira_en = calcular_expiracion(creada_en, periodo)

    assert expira_en == creada_en + periodo
    assert (expira_en - creada_en) == periodo
