"""T7/T8 startup boundary, using only an exclusively disposable PostgreSQL DB."""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app import worker
from app.infra.database import Base
from app.infra.models import (
    ManualRecoveryPilotGate,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingRecoveryOutbox,
    SessionRecording,
    User,
)
from app.infra.queue import JobQueue
from app.meetings.recovery_service import MeetingRecoveryService
from app.meetings.speaker_excerpt_service import ExcerptKeyring

PRIVATE_NOTE = "synthetic-private-note-773"
PRIVATE_AUDIO = "synthetic/private/audio-773"
PRIVATE_KEY = "synthetic-private-idempotency-773"


@pytest.fixture
async def recovery_db(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    url = os.environ.get("SAURI_OUTBOX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires exclusively disposable PostgreSQL SAURI_OUTBOX_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "recovery_773"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await engine.dispose()


@pytest.fixture
async def candidate(recovery_db: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    owner, meeting_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with recovery_db() as session, session.begin():
        session.add(User(id=owner, email="synthetic773@sauri.local", name="Synthetic773",
                         password_hash="not-a-password", is_sales=True, created_at=now))
        await session.flush()
        session.add(Meeting(id=meeting_id, meet_link="https://example.invalid/773", origin="link",
                            title=PRIVATE_NOTE, process_state="queued", created_by=owner, created_at=now))
        await session.flush()
        session.add(SessionRecording(id=str(uuid.uuid4()), meeting_id=meeting_id,
                                     idempotency_key=str(uuid.uuid4()), capture_origin="web_upload",
                                     audio_ref=PRIVATE_AUDIO, duration_seconds=1, interrupted=False,
                                     finished_at=now, expires_at=now + timedelta(days=7)))
        session.add(MeetingProcessingClaim(meeting_id=meeting_id, generation=4))
        session.add(ManualRecoveryPilotGate(id=1, status="disabled", allowed_meeting_id=meeting_id,
                                           authorized_by=owner, armed_at=now, updated_at=now))
    monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "pilot")
    monkeypatch.setenv("SAURI_RECOVERY_PILOT_MEETING_ID", meeting_id)
    return meeting_id, owner


async def accept(candidate: tuple[str, str]) -> dict[str, Any]:
    store = AsyncMock()
    store.inspect.return_value = "available"
    result = await MeetingRecoveryService(lambda: store).recover(*candidate, PRIVATE_KEY)
    assert result["status"] == "accepted"
    store.get.assert_not_awaited()
    return dict(result)


async def snapshot(factory: async_sessionmaker[AsyncSession]) -> dict[str, list[tuple[Any, ...]]]:
    async with factory() as session:
        return {table.name: sorted([tuple(row) for row in (await session.execute(select(table))).all()], key=repr)
                for table in Base.metadata.sorted_tables}


@pytest.fixture
def run_startup(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Awaitable[AsyncMock]]:
    """Run actual main; isolate external jobs and stop via its real signal callback."""
    queue = AsyncMock(spec=JobQueue)
    monkeypatch.setattr(worker, "create_job_queue", lambda: queue)
    monkeypatch.setattr(worker, "create_object_store", lambda: AsyncMock())
    monkeypatch.setattr(ExcerptKeyring, "from_environment", lambda: None)
    monkeypatch.setattr(worker, "start_transcription_worker", AsyncMock())
    monkeypatch.setattr(worker, "start_diarization_worker", AsyncMock())
    monkeypatch.setattr(worker, "start_retention_worker", AsyncMock())
    # Inject real PostgreSQL engine/session factories scoped to our disposable DB.
    monkeypatch.setattr(worker, "create_engine", lambda: create_async_engine(
        os.environ["SAURI_OUTBOX_TEST_DATABASE_URL"]))
    monkeypatch.setattr(worker, "create_session_factory", lambda engine: async_sessionmaker(
        engine, expire_on_commit=False))
    # No global Event replacement or OS signal handlers are installed.
    async def run() -> AsyncMock:
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: callback())
        await asyncio.wait_for(worker.main(), timeout=5)
        queue.connect.assert_awaited()
        queue.disconnect.assert_awaited()
        return queue

    return run


async def test_startup_delivers_committed_operation_once(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = await accept(candidate)
    before = await snapshot(recovery_db)
    # Dispatcher delivers accepted intent, independent of later runtime arming.
    monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "disabled")
    monkeypatch.delenv("SAURI_RECOVERY_PILOT_MEETING_ID")
    queue = await run_startup()
    assert queue.publish.await_count == 1
    topic, payload = queue.publish.await_args.args
    assert topic == "transcribe"
    assert payload["operation_id"] == payload["job_id"] == receipt["operation_id"]
    assert payload["generation"] == 5 and payload["meeting_id"] == candidate[0]
    assert payload["owner_id"] == candidate[1]
    async with recovery_db() as session:
        recording = (await session.scalars(select(SessionRecording))).one()
        assert payload["recording_id"] == recording.id
        outbox = (await session.scalars(select(MeetingRecoveryOutbox))).one()
        assert outbox.delivery_status == "published" and outbox.attempts == 1
        assert (await session.scalars(select(MeetingRecoveryOperation))).one().id == receipt["operation_id"]
    assert set(payload) == {"operation_id", "job_id", "generation", "meeting_id", "owner_id", "recording_id"}
    after = await snapshot(recovery_db)
    for table in before.keys() - {"meeting_recovery_outbox"}:
        assert before[table] == after[table], table
    await run_startup()
    assert queue.publish.await_count == 1  # no republish on ordinary restart
    for sentinel in (PRIVATE_NOTE, PRIVATE_AUDIO, PRIVATE_KEY, "synthetic773@sauri.local"):
        assert sentinel not in repr(payload) + caplog.text


@pytest.mark.parametrize("reason", ["empty", "disabled", "non_owner", "rollback"])
async def test_startup_does_not_initiate_or_publish_uncommitted_recovery(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], monkeypatch: pytest.MonkeyPatch, reason: str,
) -> None:
    if reason == "disabled":
        monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "disabled")
        store = AsyncMock()
        result = await MeetingRecoveryService(lambda: store).recover(*candidate, PRIVATE_KEY)
        assert result["status"] == "pilot_not_armed"
    elif reason == "non_owner":
        result = await MeetingRecoveryService().recover(candidate[0], str(uuid.uuid4()), PRIVATE_KEY)
        assert result["status"] == "not_found"
    elif reason == "rollback":
        # Real recover() flushes operation/outbox; a commit error rolls them back.
        observed_pending = []

        def reject_commit(session: Session) -> None:
            row = session.scalar(select(MeetingRecoveryOutbox))
            assert row is not None and row.delivery_status == "pending"
            observed_pending.append(row.operation_id)
            raise SQLAlchemyError("synthetic commit refusal")

        event.listen(Session, "before_commit", reject_commit)
        try:
            store = AsyncMock()
            store.inspect.return_value = "available"
            result = await MeetingRecoveryService(lambda: store).recover(*candidate, PRIVATE_KEY)
            assert result["status"] == "eligibility_unverified"
            assert len(observed_pending) == 1
        finally:
            event.remove(Session, "before_commit", reject_commit)
    before = await snapshot(recovery_db)
    queue = await run_startup()
    queue.publish.assert_not_awaited()
    assert await snapshot(recovery_db) == before
    async with recovery_db() as session:
        assert not (await session.scalars(select(MeetingRecoveryOperation))).all()
        assert not (await session.scalars(select(MeetingRecoveryOutbox))).all()


async def test_uncommitted_service_writes_are_invisible_to_startup(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]],
) -> None:
    store = AsyncMock()
    store.inspect.return_value = "available"
    async with recovery_db() as session:
        await session.begin()
        receipt = await MeetingRecoveryService(lambda: store)._recover(session, *candidate, PRIVATE_KEY)
        assert receipt["status"] == "accepted"
        assert (await session.scalars(select(MeetingRecoveryOutbox))).one().delivery_status == "pending"
        queue = await run_startup()
        queue.publish.assert_not_awaited()
        await session.rollback()
    async with recovery_db() as session:
        assert not (await session.scalars(select(MeetingRecoveryOutbox))).all()


@pytest.mark.parametrize("case", ["operation_status", "generation", "claim", "owner", "recording", "topic"])
async def test_unverified_outbox_binding_does_not_publish_or_mutate(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], case: str,
) -> None:
    await accept(candidate)
    async with recovery_db() as session, session.begin():
        operation = (await session.scalars(select(MeetingRecoveryOperation))).one()
        outbox = (await session.scalars(select(MeetingRecoveryOutbox))).one()
        claim = (await session.scalars(select(MeetingProcessingClaim))).one()
        meeting = (await session.scalars(select(Meeting))).one()
        if case == "operation_status":
            operation.status = "completed"
        elif case == "generation":
            outbox.processing_generation += 1
        elif case == "claim":
            claim.claim_kind = "transcription"
        elif case == "owner":
            meeting.created_by = "synthetic-other-owner"
        elif case == "recording":
            await session.delete((await session.scalars(select(SessionRecording))).one())
        elif case == "topic":
            outbox.topic = "diarize"
    before = await snapshot(recovery_db)
    queue = await run_startup()
    queue.publish.assert_not_awaited()
    assert await snapshot(recovery_db) == before


async def test_publish_failure_keeps_pending_without_leaking_exception(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await accept(candidate)
    queue = AsyncMock(spec=JobQueue)
    queue.publish.side_effect = RuntimeError(PRIVATE_AUDIO + PRIVATE_NOTE)
    monkeypatch.setattr(worker, "create_job_queue", lambda: queue)
    before = await snapshot(recovery_db)
    # Own startup wrapper checks its default queue; use actual main for this failure.
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: callback())
    await asyncio.wait_for(worker.main(), 5)
    queue.disconnect.assert_awaited_once()
    queue.publish.assert_awaited_once()
    async with recovery_db() as session:
        outbox = (await session.scalars(select(MeetingRecoveryOutbox))).one()
        operation = (await session.scalars(select(MeetingRecoveryOperation))).one()
        assert outbox.delivery_status == "pending" and outbox.attempts == 1
        assert operation.status == "dispatch_pending" and operation.reason_code == "publish_failed"
    after = await snapshot(recovery_db)
    for table in before.keys() - {"meeting_recovery_outbox", "meeting_recovery_operations"}:
        assert before[table] == after[table], table
    assert PRIVATE_AUDIO not in caplog.text and PRIVATE_NOTE not in caplog.text


async def test_parallel_dispatchers_publish_initial_row_once(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
) -> None:
    from app.infra.recovery_outbox import dispatch_pending_recoveries

    await accept(candidate)
    queue = AsyncMock(spec=JobQueue)
    entered, release = asyncio.Event(), asyncio.Event()

    async def publish(topic: str, payload: dict[str, Any]) -> None:
        entered.set()
        await release.wait()

    queue.publish.side_effect = publish
    first = asyncio.create_task(dispatch_pending_recoveries(queue, recovery_db))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await asyncio.wait_for(dispatch_pending_recoveries(queue, recovery_db), 5) == 0
    finally:
        release.set()
        assert await asyncio.wait_for(first, 5) == 1
    queue.publish.assert_awaited_once()


@pytest.mark.parametrize("valid", [True, False])
async def test_identifier_only_delivery_reaches_fenced_consumer(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], monkeypatch: pytest.MonkeyPatch, valid: bool,
) -> None:
    from app.transcription import worker as transcription
    from app.transcription.asr_engine import TranscriptionResult

    await accept(candidate)
    queue = await run_startup()
    payload = dict(queue.publish.await_args.args[1])
    assert "audio_ref" not in payload
    if not valid:
        payload["operation_id"] = str(uuid.uuid4())
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult()
    monkeypatch.setattr(transcription, "create_asr_engine", lambda: engine)
    await transcription._process_transcription(payload, recovery_db)
    if valid:
        engine.transcribe.assert_awaited_once()
        assert engine.transcribe.await_args.args[0] == PRIVATE_AUDIO
        await transcription._process_transcription(payload, recovery_db)
        engine.transcribe.assert_awaited_once()
    else:
        engine.transcribe.assert_not_awaited()


async def test_real_rabbitmq_carries_identifier_only_startup_delivery(
    recovery_db: async_sessionmaker[AsyncSession], candidate: tuple[str, str],
    run_startup: Callable[[], Awaitable[AsyncMock]], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from app.infra.queue_rabbitmq import RabbitMQJobQueue

    broker_url = os.environ.get("SAURI_OUTBOX_TEST_BROKER_URL")
    if not broker_url:
        pytest.skip("requires exclusively disposable RabbitMQ SAURI_OUTBOX_TEST_BROKER_URL")
    parsed = make_url(broker_url)
    assert parsed.host in {"localhost", "127.0.0.1"}
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-773-signing-key-0123456789")
    monkeypatch.setenv("ASR_MAX_RETRIES", "0")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    receipt = await accept(candidate)
    publisher = RabbitMQJobQueue(broker_url)
    monkeypatch.setattr(worker, "create_job_queue", lambda: publisher)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: callback())
    with caplog.at_level(logging.DEBUG, logger="app.infra.queue_rabbitmq"):
        await asyncio.wait_for(worker.main(), 10)
    received: list[dict[str, Any]] = []
    delivered = asyncio.Event()

    async def receive(payload: dict[str, Any]) -> None:
        received.append(payload)
        delivered.set()

    consumer = RabbitMQJobQueue(broker_url)
    try:
        await consumer.connect()
        await consumer.subscribe("transcribe", receive)
        await asyncio.wait_for(delivered.wait(), 5)
        assert len(received) == 1
        assert received[0]["operation_id"] == received[0]["job_id"] == receipt["operation_id"]
        assert received[0]["generation"] == 5
        assert set(received[0]) == {"operation_id", "job_id", "generation", "meeting_id", "owner_id", "recording_id"}
        async with recovery_db() as session:
            assert (await session.scalars(select(MeetingRecoveryOutbox))).one().delivery_status == "published"
        for sentinel in (PRIVATE_AUDIO, PRIVATE_NOTE, PRIVATE_KEY, broker_url, "synthetic-773-signing-key"):
            assert sentinel not in caplog.text
    finally:
        await consumer.disconnect()
