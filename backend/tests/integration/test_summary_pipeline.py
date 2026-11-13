"""T9/#277 RED: request transaction and recoverable dispatch on real PostgreSQL/RabbitMQ.

Run with disposable SAURI_QA_POSTGRES_URL and SAURI_QA_RABBITMQ_URL. No external
personal data, fake persistence, simulated broker confirmation, or worker/provider.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import re
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import aio_pika
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import (
    Meeting,
    MeetingSummary,
    SpeechTurn,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
    User,
)
from app.infra.queue_rabbitmq import RabbitMQJobQueue
from app.main import app


def _id() -> str:
    return str(uuid4())


def _dedicated_pg_url(raw: str) -> URL:
    parsed = make_url(raw)
    if parsed.drivername != "postgresql+asyncpg" or not re.fullmatch(
        r"sauri_t9_[a-zA-Z0-9_]+",
        parsed.database or "",
    ):
        raise ValueError("SAURI_QA_POSTGRES_URL must target a dedicated sauri_t9_ PostgreSQL database")
    return parsed


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://sauri_t9_user@localhost/production",
        "postgresql+asyncpg://localhost.sauri_t9_internal/production",
        "postgresql+asyncpg://localhost/production?sauri_t9_marker=yes",
        "postgresql+asyncpg://localhost/sauri_t9_demo/other",
        "sqlite+aiosqlite:///sauri_t9_demo",
    ],
)
def test_refuse_unsafe_postgres_target_before_connecting(url: str) -> None:
    with pytest.raises(ValueError, match="dedicated sauri_t9_"):
        _dedicated_pg_url(url)


@pytest.mark.parametrize("name", ["sauri_t9_demo", "sauri_t9_QA_277"])
def test_allow_dedicated_postgres_database_name(name: str) -> None:
    assert _dedicated_pg_url(f"postgresql+asyncpg://localhost/{name}").database == name


@pytest.fixture
async def pg_request(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str]]:
    """Fresh schema in a dedicated disposable PG database, never a shared installation."""
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    parsed = _dedicated_pg_url(url)
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if broker:
        # These RED cases inspect an empty broker. Isolate reruns after a
        # previous confirmed delivery on the same disposable test instance.
        connection = await aio_pika.connect_robust(broker)
        try:
            channel = await connection.channel()
            queue = await channel.declare_queue("summarize", durable=True)
            await queue.purge()
        finally:
            await connection.close()
    engine = create_async_engine(parsed)
    try:
        async with engine.begin() as connection:
            # Only the validated dedicated test database can contain interrupted RED debris.
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner, meeting, transcript, template = (_id() for _ in range(4))
        now = datetime.now(UTC)
        async with factory() as session, session.begin():
            session.add(
                User(
                    id=owner,
                    email=f"{owner}@example.test",
                    name="Synthetic",
                    password_hash="not-used",
                    is_sales=True,
                    created_at=now,
                )
            )
            session.add(
                Meeting(
                    id=meeting,
                    meet_link="https://meet.google.com/abc-defg-hij",
                    origin="manual",
                    calendar_invite_id=None,
                    scheduled_start_time=None,
                    process_state="completed",
                    failure_cause=None,
                    created_by=owner,
                    created_at=now,
                )
            )
            session.add(
                Transcript(
                    id=transcript,
                    meeting_id=meeting,
                    language="es-CO",
                    provider="synthetic",
                    supports_turns=False,
                    expires_at=None,
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                SummaryTemplate(
                    id=template,
                    owner_user_id=owner,
                    category_id=None,
                    name="Synthetic",
                    version=1,
                    instructions="Keep these exact words",
                    created_at=now,
                    updated_at=now,
                )
            )
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.delenv("AUTH_DISABLED", raising=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory, owner, meeting, template
    finally:
        # Dedicated disposable database only: SQLAlchemy cannot emit DROP CONSTRAINT for
        # the pre-existing unnamed use_alter=True user→template FK on PostgreSQL.
        # Recreate its schema instead of weakening production models or leaving rows.
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA public CASCADE"))
                await connection.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()


def _headers(owner: str, *, sales: bool = True) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(owner, f'{owner}@example.test', 'Synthetic', sales)}"}


@pytest.mark.asyncio
async def test_transcript_commit_alone_never_creates_summary_request(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
) -> None:
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not broker:
        pytest.skip("requires disposable RabbitMQ URL in SAURI_QA_RABBITMQ_URL")
    _, factory, _, _, _ = pg_request
    # The fixture committed an actual transcript in PostgreSQL, not a queue mock.
    async with factory() as session:
        assert (await session.scalars(select(Transcript))).one()
        assert (await session.scalars(select(SummaryRequestOutbox))).all() == []
    connection = await aio_pika.connect_robust(broker)
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue("summarize", durable=True)
        assert await queue.get(fail=False, timeout=1) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_non_sales_user_cannot_enqueue_or_publish(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
) -> None:
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not broker:
        pytest.skip("requires disposable RabbitMQ URL in SAURI_QA_RABBITMQ_URL")
    client, factory, _, _, _ = pg_request
    non_sales, meeting, transcript, template = (_id() for _ in range(4))
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            User(
                id=non_sales,
                email=f"{non_sales}@example.test",
                name="Synthetic",
                password_hash="not-used",
                is_sales=False,
                created_at=now,
            )
        )
        session.add(
            Meeting(
                id=meeting,
                meet_link="https://meet.google.com/xyz-pqrs-tuv",
                origin="manual",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=non_sales,
                created_at=now,
            )
        )
        session.add(
            Transcript(
                id=transcript,
                meeting_id=meeting,
                language="es-CO",
                provider="synthetic",
                supports_turns=False,
                expires_at=None,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            SummaryTemplate(
                id=template,
                owner_user_id=non_sales,
                category_id=None,
                name="Own synthetic template",
                version=1,
                instructions="Only synthetic content",
                created_at=now,
                updated_at=now,
            )
        )
    response = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests",
        json={"template_id": template},
        headers=_headers(non_sales, sales=False),
    )
    assert response.status_code == 403, response.text
    async with factory() as session:
        assert (await session.scalars(select(SummaryRequestOutbox))).all() == []
        user = await session.get(User, non_sales)
        assert user is not None and user.is_sales is False
    connection = await aio_pika.connect_robust(broker)
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue("summarize", durable=True)
        assert await queue.get(fail=False, timeout=1) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_denied_selection_has_no_durable_event_and_never_publishes(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
) -> None:
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not broker:
        pytest.skip("requires disposable RabbitMQ URL in SAURI_QA_RABBITMQ_URL")
    client, factory, owner, meeting, _ = pg_request
    foreign_owner, foreign_template = _id(), _id()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            User(
                id=foreign_owner,
                email=f"{foreign_owner}@example.test",
                name="Synthetic",
                password_hash="not-used",
                is_sales=True,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            SummaryTemplate(
                id=foreign_template,
                owner_user_id=foreign_owner,
                category_id=None,
                name="Private",
                version=1,
                instructions="Never disclose",
                created_at=now,
                updated_at=now,
            )
        )
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    foreign = await client.post(path, json={"template_id": foreign_template}, headers=_headers(owner))
    assert foreign.status_code == 422, foreign.text
    assert "Never disclose" not in foreign.text
    # A valid template does not override the meeting's ownership boundary.
    other_meeting = await client.post(path, json={"template_id": foreign_template}, headers=_headers(foreign_owner))
    assert other_meeting.status_code == 404, other_meeting.text
    async with factory() as session:
        assert (await session.scalars(select(SummaryRequestOutbox))).all() == []
    connection = await aio_pika.connect_robust(broker)
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue("summarize", durable=True)
        assert await queue.get(fail=False, timeout=1) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_committed_request_survives_failed_publication_and_recovery_confirmation(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not broker:
        pytest.skip("requires disposable RabbitMQ URL in SAURI_QA_RABBITMQ_URL")
    client, factory, owner, meeting, template = pg_request
    response = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests",
        json={"template_id": template},
        headers=_headers(owner),
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["event_id"]
    async with factory() as session:
        original = await session.get(SummaryRequestOutbox, event_id)
        assert original is not None
        assert original.status == "pending" and original.delivered_at is None
        assert (original.template_id, original.template_version, original.instructions_snapshot) == (
            template,
            1,
            "Keep these exact words",
        )

    # An unconnected real queue cannot confirm a publish. The dispatcher must
    # retain the committed row rather than marking it delivered or losing it.
    outbox = importlib.import_module("app.summaries.outbox")
    disconnected = RabbitMQJobQueue(broker)
    # Propagating the publish failure is acceptable; committing delivery is not.
    with suppress(RuntimeError):
        await outbox.dispatch_pending(factory, disconnected)
    async with factory() as session:
        pending = await session.get(SummaryRequestOutbox, event_id)
        assert pending is not None and pending.delivered_at is None

    # Simulate restart with a fresh DB session and a real connected broker.
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-signing-key-32-bytes-long")
    connected = RabbitMQJobQueue(broker)
    await connected.connect()
    try:
        await outbox.dispatch_pending(factory, connected)
        async with factory() as session:
            delivered = await session.get(SummaryRequestOutbox, event_id)
            assert delivered is not None and delivered.delivered_at is not None
        connection = await aio_pika.connect_robust(broker)
        try:
            channel = await connection.channel()
            queue = await channel.declare_queue("summarize", durable=True)
            message = await queue.get(timeout=5)
            assert message is not None
            payload = json.loads(message.body)
            assert {
                key: payload[key]
                for key in (
                    "event_id",
                    "meeting_id",
                    "template_id",
                    "template_version",
                    "instructions_snapshot",
                )
            } == {
                "event_id": event_id,
                "meeting_id": meeting,
                "template_id": template,
                "template_version": 1,
                "instructions_snapshot": "Keep these exact words",
            }
            await message.ack()
        finally:
            await connection.close()
    finally:
        await connected.disconnect()


@pytest.mark.asyncio
async def test_concurrent_requests_allocate_distinct_generations(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
) -> None:
    client, factory, owner, meeting, template = pg_request
    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/meetings/{meeting}/summary-requests",
                json={"template_id": template},
                headers=_headers(owner),
            )
            for _ in range(8)
        )
    )
    assert all(response.status_code == 202 for response in responses), [r.text for r in responses]
    assert sorted(response.json()["generation"] for response in responses) == list(range(1, 9))
    async with factory() as session:
        assert len((await session.scalars(select(SummaryRequestOutbox))).all()) == 8


@pytest.mark.asyncio
async def test_recovery_lifespan_delivers_after_start_and_stops_at_shutdown(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not broker:
        pytest.skip("requires disposable RabbitMQ URL in SAURI_QA_RABBITMQ_URL")
    client, factory, owner, meeting, template = pg_request
    response = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests",
        json={"template_id": template},
        headers=_headers(owner),
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["event_id"]
    monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", "synthetic:" + base64.b64encode(bytes(32)).decode())
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "synthetic")
    monkeypatch.setenv("QUEUE_BROKER_URL", broker)
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-signing-key-32-bytes-long")
    # ASGITransport does not invoke lifespan. Drive the actual FastAPI startup/shutdown
    # context, not an isolated dispatch_pending helper.
    async with app.router.lifespan_context(app):
        for _ in range(100):
            async with factory() as session:
                row = await session.get(SummaryRequestOutbox, event_id)
                if row is not None and row.delivered_at is not None:
                    break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("startup recovery did not deliver the committed event")
    assert not any(t.get_name() == "summary-outbox-recovery" and not t.done() for t in asyncio.all_tasks())
    connection = await aio_pika.connect_robust(broker)
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue("summarize", durable=True)
        message = await queue.get(timeout=5)
        assert message is not None and json.loads(message.body)["event_id"] == event_id
        await message.ack()
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_lifespan_recovers_when_disposable_broker_returns(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = os.environ.get("SAURI_QA_RABBITMQ_CONTAINER", "")
    broker = os.environ.get("SAURI_QA_RABBITMQ_URL", "")
    if not re.fullmatch(r"sauri-t10-mq-[0-9]+", container) or not broker:
        pytest.skip("requires exclusively owned disposable sauri-t10-mq container")
    client, factory, owner, meeting, template = pg_request
    response = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests", json={"template_id": template}, headers=_headers(owner)
    )
    assert response.status_code == 202
    event_id = response.json()["event_id"]
    monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", "synthetic:" + base64.b64encode(bytes(32)).decode())
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "synthetic")
    monkeypatch.setenv("QUEUE_BROKER_URL", broker)
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-signing-key-32-bytes-long")
    try:
        subprocess.run(["docker", "stop", container], check=True, capture_output=True, timeout=30)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.3)
            async with factory() as session:
                pending = await session.get(SummaryRequestOutbox, event_id)
                assert pending is not None and pending.delivered_at is None
            subprocess.run(["docker", "start", container], check=True, capture_output=True, timeout=30)
            for _ in range(150):
                async with factory() as session:
                    delivered = await session.get(SummaryRequestOutbox, event_id)
                    if delivered is not None and delivered.delivered_at is not None:
                        break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("no delivery after disposable RabbitMQ restart")
    finally:
        # Never leave the exclusively owned broker stopped even after a test failure.
        subprocess.run(["docker", "start", container], check=True, capture_output=True, timeout=30)


@pytest.mark.asyncio
async def test_request_to_persisted_content_uses_frozen_lineage(
    pg_request: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.summaries import worker

    client, factory, owner, meeting, template_id = pg_request
    response = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests", json={"template_id": template_id}, headers=_headers(owner)
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["event_id"]
    async with factory() as session, session.begin():
        transcript = (await session.scalars(select(Transcript).where(Transcript.meeting_id == meeting))).one()
        session.add(
            SpeechTurn(
                id=_id(), transcript_id=transcript.id, sequence=1, text="Synthetic transcript.", start_ms=0, end_ms=1000
            )
        )
        template = await session.get(SummaryTemplate, template_id)
        assert template is not None
        template.instructions = "Changed after request"
        template.version = 2
        event = await session.get(SummaryRequestOutbox, event_id)
        assert event is not None
        message = {
            key: getattr(event, key)
            for key in (
                "event_id",
                "meeting_id",
                "transcript_id",
                "generation",
                "template_id",
                "template_version",
                "instructions_snapshot",
            )
        }

    calls: list[tuple[str, str]] = []

    class Engine:
        async def generate(self, text: str, instructions: str) -> SimpleNamespace:
            calls.append((text, instructions))
            return SimpleNamespace(topic="Identifiable topic", key_points=["Identifiable point"])

    class Queue:
        def __init__(self) -> None:
            self.handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}

        async def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
            self.handlers[topic] = handler

    monkeypatch.setattr(worker, "create_summarization_engine", Engine)
    queue = Queue()
    await worker.start_worker(queue, factory)  # type: ignore[arg-type]  # Minimal subscription seam.
    await queue.handlers["summarize"](message)
    assert calls == [("Synthetic transcript.", "Keep these exact words")]
    async with factory() as session:
        row = (await session.scalars(select(MeetingSummary).where(MeetingSummary.event_id == event_id))).one()
        assert (row.topic, json.loads(row.key_points_json)) == ("Identifiable topic", ["Identifiable point"])
        assert (row.template_id, row.template_version, row.generation) == (template_id, 1, 1)
