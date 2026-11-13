"""T9/#277 RED: request transaction and recoverable dispatch on real PostgreSQL/RabbitMQ.

Run with disposable SAURI_QA_POSTGRES_URL and SAURI_QA_RABBITMQ_URL. No external
personal data, fake persistence, simulated broker confirmation, or worker/provider.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

import aio_pika
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SummaryRequestOutbox, SummaryTemplate, Transcript, User
from app.infra.queue_rabbitmq import RabbitMQJobQueue
from app.main import app


def _id() -> str:
    return str(uuid4())


@pytest.fixture
async def pg_request(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str]]:
    """Fresh schema in a dedicated disposable PG database, never a shared installation."""
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    if "sauri_t9_" not in url:
        pytest.fail("SAURI_QA_POSTGRES_URL must name a dedicated sauri_t9_ database")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        # This dedicated test database can contain debris from an interrupted RED run.
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner, meeting, transcript, template = (_id() for _ in range(4))
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(User(id=owner, email=f"{owner}@example.test", name="Synthetic",
                         password_hash="not-used", is_sales=True, created_at=now))
        session.add(Meeting(id=meeting, meet_link="https://meet.google.com/abc-defg-hij",
                            origin="manual", calendar_invite_id=None, scheduled_start_time=None,
                            process_state="completed", failure_cause=None, created_by=owner, created_at=now))
        session.add(Transcript(id=transcript, meeting_id=meeting, language="es-CO",
                               provider="synthetic", supports_turns=False, expires_at=None, created_at=now))
        await session.flush()
        session.add(SummaryTemplate(id=template, owner_user_id=owner, category_id=None,
                                    name="Synthetic", version=1, instructions="Keep these exact words",
                                    created_at=now, updated_at=now))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory, owner, meeting, template
    # Dedicated disposable database only: SQLAlchemy cannot emit DROP CONSTRAINT for
    # the pre-existing unnamed use_alter=True user→template FK on PostgreSQL.
    # Recreate its schema instead of weakening production models or leaving rows.
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _headers(owner: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(owner, f'{owner}@example.test', 'Synthetic', True)}"}


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
        json={"template_id": template}, headers=_headers(owner),
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["event_id"]
    async with factory() as session:
        original = await session.get(SummaryRequestOutbox, event_id)
        assert original is not None
        assert original.status == "pending" and original.delivered_at is None
        assert (original.template_id, original.template_version, original.instructions_snapshot) == (
            template, 1, "Keep these exact words")

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
            assert {key: payload[key] for key in (
                "event_id", "meeting_id", "template_id", "template_version", "instructions_snapshot",
            )} == {"event_id": event_id, "meeting_id": meeting, "template_id": template,
                  "template_version": 1, "instructions_snapshot": "Keep these exact words"}
            await message.ack()
        finally:
            await connection.close()
    finally:
        await connected.disconnect()
