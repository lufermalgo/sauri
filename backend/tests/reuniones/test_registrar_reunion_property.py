"""Property tests de registrar_reunion (service.py).

# Feature: meeting-capture-transcription, Property 1: Registro de Reunion inicia en "en cola"
# Feature: meeting-capture-transcription, Property 2: Aceptación de tipos de entrada de Reunion
Tasks: 5.5, 5.6
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.reuniones.service import registrar_reunion

meet_link_strategy = st.from_regex(r"[a-z]{3,4}-[a-z]{4}-[a-z]{3}", fullmatch=True).map(
    lambda code: f"https://meet.google.com/{code}"
)

invalid_link_strategy = st.one_of(
    st.just("http://meet.google.com/abc-defg-hij"),
    st.just("https://zoom.us/j/123456"),
    st.just(""),
    st.text(max_size=10).filter(lambda s: not s.startswith("https://meet.google.com/")),
)


# ---------------------------------------------------------------------------
# Property 1: Registro de Reunion inicia en "en cola"
# Feature: meeting-capture-transcription, Property 1: Registro de Reunion inicia en "en cola"
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(enlace=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_1_registro_inicia_en_cola(
    db_session: AsyncSession, enlace: str
) -> None:
    """Toda Reunion registrada válidamente inicia en estado 'en_cola'."""
    reunion = await registrar_reunion(
        db_session, {"enlace_meet": enlace}, creada_por="test-user"
    )

    assert reunion.estado_proceso == "en_cola"
    assert reunion.causa_fallo is None


# ---------------------------------------------------------------------------
# Property 2: Aceptación de tipos de entrada de Reunion
# Feature: meeting-capture-transcription, Property 2: Aceptación de tipos de entrada de Reunion
# Validates: Requirements 1.7
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(enlace=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_2_acepta_entrada_por_enlace(
    db_session: AsyncSession, enlace: str
) -> None:
    """Entrada por enlace directo es aceptada y produce origen='enlace'."""
    reunion = await registrar_reunion(
        db_session, {"enlace_meet": enlace}, creada_por="test-user"
    )
    assert reunion.origen == "enlace"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(enlace=meet_link_strategy, id_invitacion=st.text(min_size=1, max_size=30))
@pytest.mark.asyncio
async def test_property_2_acepta_entrada_por_calendario(
    db_session: AsyncSession, enlace: str, id_invitacion: str
) -> None:
    """Entrada por invitación de calendario es aceptada y produce origen='invitacion_calendario'."""
    hora = datetime.now(UTC) + timedelta(hours=1)
    reunion = await registrar_reunion(
        db_session,
        {
            "enlace_meet": enlace,
            "id_invitacion_calendario": id_invitacion,
            "hora_inicio_programada": hora,
        },
        creada_por="test-user",
    )
    assert reunion.origen == "invitacion_calendario"
    assert reunion.id_invitacion_calendario == id_invitacion


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(enlace=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_2_acepta_entrada_manual(
    db_session: AsyncSession, enlace: str
) -> None:
    """Solicitud manual (tipo='manual') es aceptada y produce origen='manual'."""
    reunion = await registrar_reunion(
        db_session, {"enlace_meet": enlace, "tipo": "manual"}, creada_por="test-user"
    )
    assert reunion.origen == "manual"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(enlace_invalido=invalid_link_strategy)
@pytest.mark.asyncio
async def test_property_2_rechaza_enlaces_invalidos(
    db_session: AsyncSession, enlace_invalido: str
) -> None:
    """Cualquier entrada con enlace no válido de Google Meet es rechazada."""
    with pytest.raises(ValueError):
        await registrar_reunion(
            db_session, {"enlace_meet": enlace_invalido}, creada_por="test-user"
        )
