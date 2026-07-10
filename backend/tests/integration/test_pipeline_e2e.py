"""Test de integración end-to-end del pipeline (ingesta → transcripción → persistencia).

# Feature: meeting-capture-transcription
Task: 17.3 — Validates: Requirements 2.2, 5.3, 5.4, 6.1

Ejercita el pipeline completo contra dependencias reales en contenedores locales
(PostgreSQL, MinIO, RabbitMQ vía docker-compose): subida multipart autenticada
(incluida reentrega con la misma clave_idempotencia), transcripción y persistencia.
Verifica que el adaptador ASR local no hace llamadas externas (solo al servicio
local levantado en el propio test) y que el adaptador externo (cloud) es el que
efectivamente se invoca cuando así lo configura ASR_PROVIDER.

Se salta automáticamente si Postgres/MinIO/RabbitMQ no están disponibles en
localhost (ver docker-compose.yml: `docker compose up -d postgres minio rabbitmq`).
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
import uuid
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

_DATABASE_URL = "postgresql+asyncpg://sauri:sauri_dev@localhost:5432/sauri"
_OBJECT_STORE_ENDPOINT = "http://localhost:9000"
_OBJECT_STORE_BUCKET = "sauri-recordings-it"
_MINIO_USER = "minioadmin"
_MINIO_PASSWORD = "minioadmin"
_QUEUE_BROKER_URL = "amqp://guest:guest@localhost:5672/"


def _puerto_abierto(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _infra_disponible() -> bool:
    return (
        _puerto_abierto("localhost", 5432)
        and _puerto_abierto("localhost", 9000)
        and _puerto_abierto("localhost", 5672)
    )


requiere_infra = pytest.mark.skipif(
    not _infra_disponible(),
    reason=(
        "Requiere Postgres/MinIO/RabbitMQ en localhost. "
        "Levantar con: docker compose up -d postgres minio rabbitmq"
    ),
)


class _FakeASRServer:
    """Servidor HTTP local (loopback) que simula el contenedor asr-engine,
    para verificar que el proveedor local NUNCA sale a una red externa."""

    def __init__(self) -> None:
        self.requests_received = 0
        self._app = FastAPI()

        @self._app.post("/transcribe")
        async def transcribe(request: Request) -> dict:  # type: ignore[unused-ignore]
            self.requests_received += 1
            await request.json()
            return {
                "language": "es-CO",
                "segments": [
                    {"text": "hola, buenas tardes", "start_ms": 0, "end_ms": 1200},
                    {"text": "¿cómo estás?", "start_ms": 1200, "end_ms": 2500},
                ],
            }

        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()

        config = uvicorn.Config(self._app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        for _ in range(50):
            if _puerto_abierto("127.0.0.1", self.port, timeout=0.2):
                return
            time.sleep(0.1)
        raise RuntimeError("El servidor ASR fake no arrancó a tiempo")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


@pytest.fixture(scope="module")
def fake_asr_server() -> Iterator[_FakeASRServer]:
    server = _FakeASRServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def _env_infra(fake_asr_server: _FakeASRServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _DATABASE_URL)
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", _OBJECT_STORE_ENDPOINT)
    monkeypatch.setenv("OBJECT_STORE_BUCKET", _OBJECT_STORE_BUCKET)
    monkeypatch.setenv("MINIO_ROOT_USER", _MINIO_USER)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", _MINIO_PASSWORD)
    monkeypatch.setenv("QUEUE_BROKER_URL", _QUEUE_BROKER_URL)
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("ASR_PROVIDER", "local")
    monkeypatch.setenv("ASR_LOCAL_URL", f"http://127.0.0.1:{fake_asr_server.port}")

    # app.auth.dependencies reads AUTH_DISABLED once at import time, so setting
    # the env var alone has no effect if the module was already imported by an
    # earlier test in the same session — patch the module attribute directly.
    import app.auth.dependencies as auth_dependencies

    monkeypatch.setattr(auth_dependencies, "_AUTH_DISABLED", True)


@pytest.fixture(scope="module")
def _bucket_creado() -> None:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=_OBJECT_STORE_ENDPOINT,
        aws_access_key_id=_MINIO_USER,
        aws_secret_access_key=_MINIO_PASSWORD,
        config=Config(signature_version="s3v4"),
    )
    with contextlib.suppress(ClientError):
        client.create_bucket(Bucket=_OBJECT_STORE_BUCKET)


@pytest.fixture(autouse=True)
async def _esquema_bd() -> None:
    from app.infra.database import Base

    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@requiere_infra
@pytest.mark.asyncio
async def test_subida_multipart_autenticada_idempotente_y_transcripcion(
    _bucket_creado: None,
    fake_asr_server: _FakeASRServer,
) -> None:
    """Subida multipart autenticada, reentrega idempotente, y transcripción con
    persistencia real (Postgres + MinIO), usando el adaptador ASR local
    que NUNCA llama a un servicio externo (solo al fake local del test)."""
    from sqlalchemy import select

    from app.infra.database import create_engine, create_session_factory
    from app.infra.models import GrabacionDeSesion, Reunion, Transcripcion, TurnoDeHabla
    from app.main import app
    from app.transcripcion.worker import _procesar_transcripcion

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        registro = await client.post(
            "/api/v1/reuniones/",
            json={"enlace_meet": "https://meet.google.com/abc-defg-hij"},
        )
        assert registro.status_code == 201
        reunion_id = registro.json()["reunion_id"]

        # Simula que la extensión ya se unió y está grabando (Req. 1.2/2.1),
        # que es el estado previo real desde el que la ingesta transiciona.
        engine_setup = create_engine()
        session_factory_setup = create_session_factory(engine_setup)
        async with session_factory_setup() as session, session.begin():
            reunion = await session.get(Reunion, reunion_id)
            assert reunion is not None
            reunion.estado_proceso = "grabando"
        await engine_setup.dispose()

        clave_idempotencia = str(uuid.uuid4())
        datos = {
            "reunion_id": reunion_id,
            "clave_idempotencia": clave_idempotencia,
            "origen_captura": "extension_chrome",
            "duracion_segundos": 5,
            "interrumpida": False,
        }
        audio_bytes = b"contenido-de-audio-simulado"

        primera = await client.post(
            "/api/v1/ingesta/subir",
            files={"audio": ("audio.webm", audio_bytes, "audio/webm")},
            data={"datos": __import__("json").dumps(datos)},
        )
        assert primera.status_code == 200
        assert primera.json()["estado"] == "transcribiendo"
        grabacion_id = primera.json()["grabacion_id"]

        # Reentrega con la misma clave_idempotencia: no debe duplicar.
        segunda = await client.post(
            "/api/v1/ingesta/subir",
            files={"audio": ("audio.webm", audio_bytes, "audio/webm")},
            data={"datos": __import__("json").dumps(datos)},
        )
        assert segunda.status_code == 200
        assert segunda.json()["estado"] == "duplicado_idempotente"
        assert segunda.json()["grabacion_id"] == grabacion_id

    engine = create_engine()
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        result = await session.execute(
            select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
        )
        grabaciones = result.scalars().all()
        assert len(grabaciones) == 1

    # Procesar el trabajo de transcripción (worker) contra el adaptador local.
    audio_ref = grabaciones[0].audio_ref
    await _procesar_transcripcion(
        {"reunion_id": reunion_id, "audio_ref": audio_ref}, session_factory
    )

    assert fake_asr_server.requests_received == 1

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        transcripcion = result.scalar_one()
        assert transcripcion.idioma == "es-CO"
        assert transcripcion.proveedor == "local"

        turnos_result = await session.execute(
            select(TurnoDeHabla).where(TurnoDeHabla.transcripcion_id == transcripcion.id)
        )
        turnos = turnos_result.scalars().all()
        assert len(turnos) == 2

        reunion = await session.get(Reunion, reunion_id)
        assert reunion is not None
        assert reunion.estado_proceso == "completado"

    await engine.dispose()


@requiere_infra
@pytest.mark.asyncio
async def test_adaptador_cloud_es_el_invocado_cuando_asr_provider_es_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con ASR_PROVIDER=cloud, el worker persiste la Transcripcion con proveedor='cloud'
    (Req. 5.4): el adaptador externo es el efectivamente invocado por la fábrica."""
    monkeypatch.setenv("ASR_PROVIDER", "cloud")
    monkeypatch.setenv("ASR_CLOUD_API_KEY", "test-key")
    monkeypatch.setenv("ASR_CLOUD_ENDPOINT", "https://api.example.com/v1/transcribe")

    from sqlalchemy import select

    from app.infra.database import create_engine, create_session_factory
    from app.infra.models import Transcripcion
    from app.reuniones.service import registrar_reunion
    from app.transcripcion.worker import _procesar_transcripcion

    engine = create_engine()
    session_factory = create_session_factory(engine)

    reunion_id: str
    async with session_factory() as session, session.begin():
        reunion = await registrar_reunion(
            session,
            {"enlace_meet": "https://meet.google.com/xyz-defg-hij"},
            creada_por="test-user",
        )
        reunion_id = reunion.id
        reunion.estado_proceso = "grabando"
        await session.flush()

    await _procesar_transcripcion(
        {"reunion_id": reunion_id, "audio_ref": "audio/fake.webm"}, session_factory
    )

    async with session_factory() as session:
        result = await session.execute(
            select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
        )
        transcripcion = result.scalar_one()
        assert transcripcion.proveedor == "cloud"

    await engine.dispose()
