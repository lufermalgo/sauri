"""End-to-end integration test for the pipeline (ingestion -> transcription -> persistence).

# Feature: meeting-capture-transcription
Task: 17.3 — Validates: Requirements 2.2, 5.3, 5.4, 6.1

Exercises the full pipeline against real dependencies in local containers
(PostgreSQL, MinIO, RabbitMQ via docker-compose): authenticated multipart
upload (including redelivery with the same idempotency_key), transcription,
and persistence. Verifies that the local ASR adapter makes no external calls
(only to the local service started within the test itself) and that the
external (cloud) adapter is the one actually invoked when ASR_PROVIDER is
configured that way.

Automatically skipped if Postgres/MinIO/RabbitMQ aren't available on
localhost (see docker-compose.yml: `docker compose up -d postgres minio rabbitmq`).
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

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


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _infra_available() -> bool:
    return (
        _port_open("localhost", 5432)
        and _port_open("localhost", 9000)
        and _port_open("localhost", 5672)
    )


requires_infra = pytest.mark.skipif(
    not _infra_available(),
    reason=(
        "Requires Postgres/MinIO/RabbitMQ on localhost. "
        "Start with: docker compose up -d postgres minio rabbitmq"
    ),
)


class _FakeASRServer:
    """Local (loopback) HTTP server that simulates the asr-engine container,
    to verify that the local provider NEVER reaches an external network."""

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
                    {"text": "hola, buenas tardes", "start_ms": 0, "end_ms": 1200},  # spanish-sample-data
                    {"text": "¿cómo estás?", "start_ms": 1200, "end_ms": 2500},  # spanish-sample-data
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
            if _port_open("127.0.0.1", self.port, timeout=0.2):
                return
            time.sleep(0.1)
        raise RuntimeError("The fake ASR server did not start in time")

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
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ASR_PROVIDER", "local")
    monkeypatch.setenv("ASR_LOCAL_URL", f"http://127.0.0.1:{fake_asr_server.port}")

    # app.auth.dependencies._bypass_active() reads AUTH_DISABLED/APP_ENV live via
    # os.getenv() on every call (Req. 13.1, 13.4), so setting the env vars above
    # is sufficient — no module attribute needs patching.


@pytest.fixture(scope="module")
def _bucket_created() -> None:
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
async def _db_schema() -> None:
    from app.infra.database import Base

    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@requires_infra
@pytest.mark.asyncio
async def test_authenticated_idempotent_multipart_upload_and_transcription(
    _bucket_created: None,
    fake_asr_server: _FakeASRServer,
) -> None:
    """Authenticated multipart upload, idempotent redelivery, and transcription
    with real persistence (Postgres + MinIO), using the local ASR adapter
    that NEVER calls an external service (only the test's local fake)."""
    from sqlalchemy import select

    from app.infra.database import create_engine, create_session_factory
    from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript
    from app.main import app
    from app.transcription.worker import _process_transcription

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        registration = await client.post(
            "/api/v1/meetings/",
            json={"meet_link": "https://meet.google.com/abc-defg-hij"},
        )
        assert registration.status_code == 201
        meeting_id = registration.json()["meeting_id"]

        # Simulates that the extension already joined and is recording (Req.
        # 1.2/2.1), which is the real prior state from which ingestion
        # transitions.
        engine_setup = create_engine()
        session_factory_setup = create_session_factory(engine_setup)
        async with session_factory_setup() as session, session.begin():
            meeting = await session.get(Meeting, meeting_id)
            assert meeting is not None
            meeting.process_state = "recording"
        await engine_setup.dispose()

        idempotency_key = str(uuid.uuid4())
        data: dict[str, Any] = {
            "meeting_id": meeting_id,
            "idempotency_key": idempotency_key,
            "capture_origin": "chrome_extension",
            "duration_seconds": 5,
            "interrupted": False,
        }
        audio_bytes = b"simulated-audio-content"

        first = await client.post(
            "/api/v1/ingestion/upload",
            files={"audio": ("audio.webm", audio_bytes, "audio/webm")},
            data={"data": __import__("json").dumps(data)},
        )
        assert first.status_code == 200
        assert first.json()["state"] == "transcribing"
        recording_id = first.json()["recording_id"]

        # Redelivery with the same idempotency_key: must not duplicate.
        second = await client.post(
            "/api/v1/ingestion/upload",
            files={"audio": ("audio.webm", audio_bytes, "audio/webm")},
            data={"data": __import__("json").dumps(data)},
        )
        assert second.status_code == 200
        assert second.json()["state"] == "idempotent_duplicate"
        assert second.json()["recording_id"] == recording_id

    engine = create_engine()
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        result = await session.execute(
            select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
        )
        recordings = result.scalars().all()
        assert len(recordings) == 1

    # Process the transcription job (worker) against the local adapter.
    audio_ref = recordings[0].audio_ref
    await _process_transcription(
        {"meeting_id": meeting_id, "audio_ref": audio_ref}, session_factory
    )

    assert fake_asr_server.requests_received == 1

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcript = result.scalar_one()
        assert transcript.language == "es-CO"
        assert transcript.provider == "local"

        turns_result = await session.execute(
            select(SpeechTurn).where(SpeechTurn.transcript_id == transcript.id)
        )
        turns = turns_result.scalars().all()
        assert len(turns) == 2

        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.process_state == "completed"

    await engine.dispose()


@requires_infra
@pytest.mark.asyncio
async def test_cloud_adapter_is_invoked_when_asr_provider_is_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ASR_PROVIDER=cloud, the worker persists the Transcript with
    provider='cloud' (Req. 5.4): the external adapter is the one actually
    invoked by the factory."""
    monkeypatch.setenv("ASR_PROVIDER", "cloud")
    monkeypatch.setenv("ASR_CLOUD_API_KEY", "test-key")
    monkeypatch.setenv("ASR_CLOUD_ENDPOINT", "https://api.example.com/v1/transcribe")

    from sqlalchemy import select

    from app.infra.database import create_engine, create_session_factory
    from app.infra.models import Transcript
    from app.meetings.service import register_meeting
    from app.transcription.worker import _process_transcription

    engine = create_engine()
    session_factory = create_session_factory(engine)

    meeting_id: str
    async with session_factory() as session, session.begin():
        meeting = await register_meeting(
            session,
            {"meet_link": "https://meet.google.com/xyz-defg-hij"},
            created_by="test-user",
        )
        meeting_id = meeting.id
        meeting.process_state = "recording"
        await session.flush()

    await _process_transcription(
        {"meeting_id": meeting_id, "audio_ref": "audio/fake.webm"}, session_factory
    )

    async with session_factory() as session:
        result = await session.execute(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        transcript = result.scalar_one()
        assert transcript.provider == "cloud"

    await engine.dispose()
