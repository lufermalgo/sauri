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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
    monkeypatch.setattr(worker.ExcerptKeyring, "from_environment", lambda: None)
    monkeypatch.setattr(worker, "start_transcription_worker", AsyncMock())
    monkeypatch.setattr(worker, "start_diarization_worker", AsyncMock())
    monkeypatch.setattr(worker, "start_retention_worker", AsyncMock())
    # Factories stay real, but DATABASE_URL points exclusively to our disposable DB.
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
) -> None:
    receipt = await accept(candidate)
    before = await snapshot(recovery_db)
    # Dispatcher delivers accepted intent, independent of later runtime arming.
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
