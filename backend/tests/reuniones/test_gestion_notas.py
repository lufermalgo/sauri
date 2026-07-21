"""Contrato de PATCH/DELETE /api/v1/reuniones/{id} — administrar Mis_Notas (renombrar, eliminar).

Validates: gestión de notas (renombrar y eliminar) desde el Side_Panel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import crear_token
from app.infra.models import (
    AsignacionDeHablante,
    Diarizacion,
    GrabacionDeSesion,
    Hablante,
    Reunion,
    Transcripcion,
    TurnoDeHabla,
)

USUARIO_ID = "user-gestion-notas"
OTRO_USUARIO_ID = "otro-usuario"


def _auth_header(usuario_id: str = USUARIO_ID) -> dict[str, str]:
    token = crear_token(usuario_id, "gestion@sauri.local", "Gestion Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _session_factory(api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _crear_reunion(api_db_url: str, reunion_id: str, creada_por: str = USUARIO_ID) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    async with session_factory() as session, session.begin():
        session.add(
            Reunion(
                id=reunion_id,
                enlace_meet="https://meet.google.com/abc-defg-hij",
                titulo="Reunión de prueba",
                origen="enlace",
                id_invitacion_calendario=None,
                hora_inicio_programada=None,
                estado_proceso="completado",
                causa_fallo=None,
                creada_por=creada_por,
                creada_en=datetime.now(UTC),
            )
        )
    await engine.dispose()


# ---------------------------------------------------------------------------
# PATCH /{reunion_id} — renombrar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renombrar_200_actualiza_titulo(api_client: AsyncClient, api_db_url: str):
    reunion_id = str(uuid.uuid4())
    await _crear_reunion(api_db_url, reunion_id)

    resp = await api_client.patch(
        f"/api/v1/reuniones/{reunion_id}",
        json={"titulo": "Reunión Comercial Renombrada"},
        headers=_auth_header(),
    )
    assert resp.status_code == 200
    assert resp.json()["titulo"] == "Reunión Comercial Renombrada"

    listado = await api_client.get("/api/v1/reuniones/", headers=_auth_header())
    assert listado.json()[0]["titulo"] == "Reunión Comercial Renombrada"


@pytest.mark.asyncio
async def test_renombrar_404_reunion_inexistente(api_client: AsyncClient):
    resp = await api_client.patch(
        f"/api/v1/reuniones/{uuid.uuid4()}",
        json={"titulo": "X"},
        headers=_auth_header(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_renombrar_404_reunion_de_otro_usuario(api_client: AsyncClient, api_db_url: str):
    reunion_id = str(uuid.uuid4())
    await _crear_reunion(api_db_url, reunion_id, creada_por=OTRO_USUARIO_ID)

    resp = await api_client.patch(
        f"/api/v1/reuniones/{reunion_id}",
        json={"titulo": "Intento ajeno"},
        headers=_auth_header(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_renombrar_422_titulo_vacio(api_client: AsyncClient, api_db_url: str):
    reunion_id = str(uuid.uuid4())
    await _crear_reunion(api_db_url, reunion_id)

    resp = await api_client.patch(
        f"/api/v1/reuniones/{reunion_id}",
        json={"titulo": ""},
        headers=_auth_header(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_renombrar_requiere_autenticacion(api_client: AsyncClient):
    resp = await api_client.patch(
        f"/api/v1/reuniones/{uuid.uuid4()}", json={"titulo": "X"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /{reunion_id} — eliminar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eliminar_204_borra_la_reunion(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:1")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_ROOT_USER", "test")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")

    reunion_id = str(uuid.uuid4())
    await _crear_reunion(api_db_url, reunion_id)

    resp = await api_client.delete(f"/api/v1/reuniones/{reunion_id}", headers=_auth_header())
    assert resp.status_code == 204

    listado = await api_client.get("/api/v1/reuniones/", headers=_auth_header())
    assert listado.json() == []


@pytest.mark.asyncio
async def test_eliminar_404_reunion_inexistente(api_client: AsyncClient):
    resp = await api_client.delete(f"/api/v1/reuniones/{uuid.uuid4()}", headers=_auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eliminar_404_reunion_de_otro_usuario(api_client: AsyncClient, api_db_url: str):
    reunion_id = str(uuid.uuid4())
    await _crear_reunion(api_db_url, reunion_id, creada_por=OTRO_USUARIO_ID)

    resp = await api_client.delete(f"/api/v1/reuniones/{reunion_id}", headers=_auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eliminar_requiere_autenticacion(api_client: AsyncClient):
    resp = await api_client.delete(f"/api/v1/reuniones/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_eliminar_con_diarizacion_completa_no_viola_fk(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    """Reunion con Transcripcion + Diarizacion + Hablante + AsignacionDeHablante +
    GrabacionDeSesion debe poder eliminarse sin violar las FK que no tienen
    ondelete=CASCADE (diarizaciones.reunion_id, diarizaciones.transcripcion_id,
    asignaciones_de_hablante.turno_id)."""
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:1")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_ROOT_USER", "test")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")

    reunion_id = str(uuid.uuid4())
    transcripcion_id = str(uuid.uuid4())
    diarizacion_id = str(uuid.uuid4())
    turno_id = str(uuid.uuid4())
    hablante_id = str(uuid.uuid4())
    ahora = datetime.now(UTC)

    session_factory, engine = await _session_factory(api_db_url)
    async with session_factory() as session, session.begin():
        session.add(
            Reunion(
                id=reunion_id,
                enlace_meet="https://meet.google.com/abc-defg-hij",
                titulo="Con diarización",
                origen="enlace",
                id_invitacion_calendario=None,
                hora_inicio_programada=None,
                estado_proceso="completado",
                causa_fallo=None,
                creada_por=USUARIO_ID,
                creada_en=ahora,
            )
        )
        session.add(
            GrabacionDeSesion(
                id=str(uuid.uuid4()),
                reunion_id=reunion_id,
                clave_idempotencia=str(uuid.uuid4()),
                origen_captura="extension_chrome",
                audio_ref="grabaciones/audio.webm",
                video_ref=None,
                duracion_segundos=10,
                interrumpida=False,
                expira_en=None,
                finalizada_en=ahora,
            )
        )
        session.add(
            Transcripcion(
                id=transcripcion_id,
                reunion_id=reunion_id,
                idioma="es-CO",
                proveedor="local",
                soporta_turnos=True,
                expira_en=None,
                creada_en=ahora,
            )
        )
        session.add(
            TurnoDeHabla(
                id=turno_id,
                transcripcion_id=transcripcion_id,
                texto="Hola",
                inicio_ms=0,
                fin_ms=1000,
                orden=0,
            )
        )
        session.add(
            Diarizacion(
                id=diarizacion_id,
                reunion_id=reunion_id,
                transcripcion_id=transcripcion_id,
                proveedor="local",
                num_hablantes=1,
                estado_diarizacion="completada",
                causa_fallo=None,
                creada_en=ahora,
                actualizada_en=ahora,
            )
        )
        session.add(
            Hablante(
                id=hablante_id,
                diarizacion_id=diarizacion_id,
                etiqueta_cruda="SPEAKER_00",
                etiqueta="Hablante 1",
                orden=1,
            )
        )
        session.add(
            AsignacionDeHablante(
                id=str(uuid.uuid4()),
                diarizacion_id=diarizacion_id,
                turno_id=turno_id,
                hablante_id=hablante_id,
            )
        )
    await engine.dispose()

    resp = await api_client.delete(f"/api/v1/reuniones/{reunion_id}", headers=_auth_header())
    assert resp.status_code == 204

    listado = await api_client.get("/api/v1/reuniones/", headers=_auth_header())
    assert listado.json() == []
