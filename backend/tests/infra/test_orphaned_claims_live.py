"""Orphaned processing recovers on a real PostgreSQL and a real RabbitMQ (#1166).

Needs disposable services: SAURI_QA_POSTGRES_URL (database name containing ``sauri_qa``) and
SAURI_QA_RABBITMQ_URL. Skipped otherwise. The queues named transcribe/diarize are deleted before and after.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aio_pika
import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.infra.models import Meeting, MeetingProcessingClaim, SessionRecording, StateHistory, Transcript
from app.infra.orphan_sweeper import OrphanSweeper
from app.infra.queue_rabbitmq import RabbitMQJobQueue
from app.transcription.asr_engine import ASRCapabilities, TranscriptionResult, TranscriptionSegment
from app.transcription.worker import start_worker
from app.worker import stop_gracefully

BACKEND = Path(__file__).resolve().parents[2]
TOPICS = ("transcribe", "transcribe.defer", "transcribe.failed", "diarize")

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def factory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw or not os.environ.get("SAURI_QA_RABBITMQ_URL"):
        pytest.skip("requires disposable PostgreSQL and RabbitMQ in SAURI_QA_POSTGRES_URL / SAURI_QA_RABBITMQ_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_orphans_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    target = url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)
    engine = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        monkeypatch.setenv("DATABASE_URL", target)
        await asyncio.to_thread(command.upgrade, Config(str(BACKEND / "alembic.ini")), "head")
        engine = create_async_engine(target, poolclass=NullPool)
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def broker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RabbitMQJobQueue]:
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-test-key-0123456789abcdef")
    monkeypatch.setenv("QUEUE_DEFER_SECONDS", "1")
    monkeypatch.setenv("ASR_MAX_RETRIES", "0")
    url = os.environ["SAURI_QA_RABBITMQ_URL"]
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        for topic in TOPICS:  # deleted, not purged: the app declares the parking queues with its own arguments
            await channel.queue_delete(topic)
    queue = RabbitMQJobQueue(url)
    await queue.connect()
    try:
        yield queue
    finally:
        await queue.stop_consuming()
        await queue.cancel_in_flight()
        await queue.disconnect()
        async with await aio_pika.connect_robust(url) as cleanup:
            channel = await cleanup.channel()
            for topic in TOPICS:
                await channel.queue_delete(topic)


async def _eventually(check: Callable[[], Awaitable[bool]], timeout_s: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not await check():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.1)


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, claim_id: str | None, claim_kind: str | None,
    expires_at: datetime | None, generation: int = 4,
) -> dict[str, object]:
    meeting_id, owner_id, recording_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    entered = datetime.now(UTC) - timedelta(hours=1)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="transcribing", failure_cause=None,
            created_by=owner_id, created_at=entered,
        ))
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()), capture_origin="manual_upload",
            audio_ref="recordings/qa", video_ref=None, duration_seconds=60, interrupted=False, expires_at=None,
            finished_at=entered,
        ))
        session.add(StateHistory(
            id=str(uuid.uuid4()), meeting_id=meeting_id, state="transcribing", failure_cause=None, occurred_at=entered,
        ))
        session.add(MeetingProcessingClaim(
            meeting_id=meeting_id, generation=generation, claim_id=claim_id, claim_kind=claim_kind,
            claim_expires_at=expires_at,
        ))
    return {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id, "audio_ref": "recordings/qa",
        "generation": generation, "job_id": str(uuid.uuid4()),
    }


def _asr(delay_s: float = 0.0) -> AsyncMock:
    engine = AsyncMock()

    async def transcribe(*args: object, **kwargs: object) -> TranscriptionResult:
        await asyncio.sleep(delay_s)
        return TranscriptionResult(
            segments=[TranscriptionSegment(text="hola", start_ms=0, end_ms=1)], language="es", supports_turns=True,
        )

    engine.transcribe.side_effect = transcribe
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))
    return engine


def _transcribed(factory: async_sessionmaker[AsyncSession], meeting_id: object) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        async with factory() as session:
            meeting = await session.get(Meeting, str(meeting_id))
            return meeting is not None and meeting.process_state == "completed"
    return check


async def test_the_2026_11_16_stuck_meeting_resumes_when_its_message_is_redelivered(
    factory: async_sessionmaker[AsyncSession], broker: RabbitMQJobQueue,
) -> None:
    # claim_id set, claim_expires_at NULL: exactly what the recreated worker left behind.
    message = await _seed(factory, claim_id=str(uuid.uuid4()), claim_kind="transcription", expires_at=None)
    with patch("app.transcription.worker.create_asr_engine", return_value=_asr()):
        await start_worker(broker, factory)
        await broker.publish("transcribe", message)
        await _eventually(_transcribed(factory, message["meeting_id"]))
    assert await broker.pending_count("diarize") == 1  # and it moved on to speaker identification


async def test_a_redelivery_that_meets_a_live_lease_waits_and_is_processed_once_the_lease_lapses(
    factory: async_sessionmaker[AsyncSession], broker: RabbitMQJobQueue,
) -> None:
    holder = str(uuid.uuid4())
    message = await _seed(
        factory, claim_id=holder, claim_kind="transcription", expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    engine = _asr()
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await start_worker(broker, factory)
        await broker.publish("transcribe", message)
        await asyncio.sleep(3.5)  # several deferrals (1 s each): not processed, and not lost either
        assert engine.transcribe.await_count == 0
        async with factory() as session:
            assert (await session.get(Meeting, str(message["meeting_id"]))).process_state == "transcribing"  # type: ignore[union-attr]

        async with factory() as session, session.begin():  # the holder dies: its lease runs out
            await session.execute(update(MeetingProcessingClaim).where(
                MeetingProcessingClaim.meeting_id == message["meeting_id"],
            ).values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await _eventually(_transcribed(factory, message["meeting_id"]))
    assert engine.transcribe.await_count == 1


async def test_a_lost_message_is_republished_by_the_sweeper_and_the_meeting_completes(
    factory: async_sessionmaker[AsyncSession], broker: RabbitMQJobQueue,
) -> None:
    message = await _seed(factory, claim_id=None, claim_kind=None, expires_at=None)
    sweeper = OrphanSweeper(factory, broker, orphan_after_s=60, max_attempts=3, backoff_s=0, max_age_s=86400)
    with patch("app.transcription.worker.create_asr_engine", return_value=_asr()):
        await start_worker(broker, factory)
        assert await sweeper.sweep() == [f"republished:transcription:{message['meeting_id']}"]
        await _eventually(_transcribed(factory, message["meeting_id"]))


async def test_stopping_a_worker_mid_job_gives_the_claim_and_the_message_back_for_the_next_worker(
    factory: async_sessionmaker[AsyncSession], broker: RabbitMQJobQueue,
) -> None:
    message = await _seed(factory, claim_id=None, claim_kind=None, expires_at=None)
    slow = _asr(delay_s=30)
    with patch("app.transcription.worker.create_asr_engine", return_value=slow):
        await start_worker(broker, factory)
        await broker.publish("transcribe", message)

        async def running() -> bool:
            return slow.transcribe.await_count == 1
        await _eventually(running)

        assert await stop_gracefully(broker, 0.3) is False  # the grace period ran out

    async def released() -> bool:
        async with factory() as session:
            claim = await session.get(MeetingProcessingClaim, str(message["meeting_id"]))
            return claim is not None and claim.claim_id is None
    await _eventually(released)
    await _eventually(_requeued(broker))
    async with factory() as session:
        assert await session.scalar(select(Transcript.id)) is None
        assert (await session.get(Meeting, str(message["meeting_id"]))).process_state == "transcribing"  # type: ignore[union-attr]

    # The next worker takes the very same message and finishes the job.
    resumed = RabbitMQJobQueue(os.environ["SAURI_QA_RABBITMQ_URL"])
    await resumed.connect()
    try:
        with patch("app.transcription.worker.create_asr_engine", return_value=_asr()):
            await start_worker(resumed, factory)
            await _eventually(_transcribed(factory, message["meeting_id"]))
    finally:
        await resumed.stop_consuming()
        await resumed.disconnect()


def _requeued(queue: RabbitMQJobQueue) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return await queue.pending_count("transcribe") == 1
    return check
