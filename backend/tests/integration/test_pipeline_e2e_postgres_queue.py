"""Recording-to-summary pipeline on a migrated disposable PG, with fake engines only.

The upload/object-store transport is not part of this test: no disposable S3 was supplied.
All five production consumers, their persistence, and the outbox use the real database/queue.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from app.diarization.diarization_engine import DiarizationCapabilities, DiarizationResult, SpeakerSegment
from app.diarization.worker import start_worker as start_diarization
from app.infra.models import (
    Diarization,
    JobMessage,
    Meeting,
    MeetingProcessingClaim,
    MeetingSummary,
    SpeechTurn,
    SummaryRequestOutbox,
    Transcript,
    User,
)
from app.infra.orphan_sweeper import OrphanSweeper
from app.infra.queue import create_job_queue
from app.infra.queue_postgres import PostgresJobQueue
from app.summaries.engine import SummaryAnswer
from app.summaries.outbox import dispatch_pending
from app.summaries.passages import Passage, validate_citations
from app.summaries.worker import start_worker as start_summary
from app.transcription.worker import start_worker as start_transcription
from app.worker import DEFAULT_SHUTDOWN_GRACE_SECONDS, stop_gracefully
from tests.infra.test_orphaned_claims_live import _asr, _seed, _transcribed
from tests.infra.test_queue_postgres import eventually, pg_url  # noqa: F401 - shared disposable database fixture


async def test_recording_to_summary_with_five_consumers(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    monkeypatch.setenv("QUEUE_KIND", "postgres")
    queue = create_job_queue()
    assert isinstance(queue, PostgresJobQueue)
    await queue.connect()
    factory = queue._factory
    asr = _asr()
    diar = AsyncMock()
    diar.capabilities = MagicMock(return_value=DiarizationCapabilities(is_local=True, provider_name="synthetic"))
    diar.diarize.return_value = DiarizationResult(segments=[SpeakerSegment("A", 0, 1000)], speaker_count=1)
    summary = AsyncMock()

    async def generate(passages: list[Passage], instructions: str, route: Any = None) -> SummaryAnswer:
        assert passages and instructions and route is None
        return SummaryAnswer(validate_citations({
            "topic": "Synthetic topic", "conclusion": "Synthetic conclusion",
            "key_points": [{
                "title": "Synthetic point", "items": [{"text": "Synthetic detail"}],
                "sources": [{"passage_id": passages[0].passage_id}],
            }],
        }, passages), "synthetic", "test-model")

    summary.generate.side_effect = generate
    monkeypatch.setattr("app.transcription.worker.create_asr_engine", lambda: asr)
    monkeypatch.setattr("app.diarization.worker.create_diarization_engine", lambda: diar)
    monkeypatch.setattr("app.summaries.worker.create_summarization_engine", lambda: summary)
    try:
        message = await _seed(factory, claim_id=None, claim_kind=None, expires_at=None)
        async with factory() as session, session.begin():
            session.add(User(
                id=message["owner_id"], email="synthetic@example.test", name="Synthetic", password_hash="unused",
                created_at=datetime.now(UTC),
            ))
        await start_transcription(queue, factory)
        await start_diarization(queue, factory)
        await start_summary(queue, factory)
        assert len(queue._consumers) == 5
        await queue.publish("transcribe", message)

        async def summary_requested() -> bool:
            async with factory() as session:
                return await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1

        await eventually(summary_requested)
        assert await dispatch_pending(factory, queue) == 1

        async def summarized() -> bool:
            async with factory() as session:
                return await session.scalar(select(func.count()).select_from(MeetingSummary)) == 1

        await eventually(summarized)
        # Redelivery goes through the real queue; production fences prevent repeated inference.
        await queue.publish("transcribe", message)

        async def drained() -> bool:
            async with factory() as session:
                return await session.scalar(select(func.count()).select_from(JobMessage)) == 0

        await eventually(drained)
        assert asr.transcribe.await_count == diar.diarize.await_count == summary.generate.await_count == 1
        async with factory() as session:
            assert (await session.get(Meeting, message["meeting_id"])).process_state == "completed"
            assert await session.scalar(select(func.count()).select_from(Transcript)) == 1
            assert await session.scalar(select(func.count()).select_from(SpeechTurn)) == 1
            assert (await session.scalar(select(Diarization))).diarization_state == "completed"
            assert (await session.scalar(select(SummaryRequestOutbox))).status == "succeeded"
        # No consumer drains join: exactly one durable row per publication, even across reconnect.
        for index in range(3):
            await queue.publish("join", {"synthetic_index": index})
        assert await stop_gracefully(queue, DEFAULT_SHUTDOWN_GRACE_SECONDS)
        await queue.disconnect()
        await queue.connect()
        assert await queue.pending_count("join") == 3
    finally:
        await queue.disconnect()


async def test_orphan_sweeper_observes_pending_count_then_repairs_lost_delivery(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    factory = queue._factory
    monkeypatch.setattr("app.transcription.worker.create_asr_engine", _asr)
    try:
        message = await _seed(factory, claim_id=None, claim_kind=None, expires_at=None)
        sweeper = OrphanSweeper(factory, queue, orphan_after_s=60, max_attempts=3, backoff_s=0, max_age_s=86400)
        await queue.publish("transcribe", message)
        assert await sweeper.sweep() == []
        # Simulate a lost message without changing the orphan's persisted processing state.
        delivery = await queue._claim("transcribe")
        assert delivery is not None
        await queue._settle(delivery, "ack")
        assert await sweeper.sweep() == [f"republished:transcription:{message['meeting_id']}"]
        await start_transcription(queue, factory)
        await eventually(_transcribed(factory, message["meeting_id"]))
        await queue.stop_consuming()
        assert await queue.wait_idle(5)
        assert await queue.pending_count("diarize") == 1
    finally:
        await queue.disconnect()


async def test_worker_shutdown_releases_processing_claim_and_delivery(
    pg_url: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    queue = PostgresJobQueue(pg_url)
    await queue.connect()
    factory = queue._factory
    started = asyncio.Event()
    asr = _asr()

    async def slow(*args: Any, **kwargs: Any) -> None:
        started.set()
        await asyncio.Event().wait()

    asr.transcribe.side_effect = slow
    monkeypatch.setattr("app.transcription.worker.create_asr_engine", lambda: asr)
    try:
        message = await _seed(factory, claim_id=None, claim_kind=None, expires_at=None)
        await start_transcription(queue, factory)
        await queue.publish("transcribe", message)
        await asyncio.wait_for(started.wait(), 5)
        assert DEFAULT_SHUTDOWN_GRACE_SECONDS == 540
        assert not await stop_gracefully(queue, 0.01)
        assert await queue.pending_count("transcribe") == 1
        async with factory() as session:
            assert (await session.get(MeetingProcessingClaim, message["meeting_id"])).claim_id is None
            assert await session.scalar(select(func.count()).select_from(Transcript)) == 0
        await queue.disconnect()
        await queue.connect()
        monkeypatch.setattr("app.transcription.worker.create_asr_engine", _asr)
        await start_transcription(queue, factory)
        await eventually(_transcribed(factory, message["meeting_id"]))
        assert await stop_gracefully(queue, 5)
    finally:
        await queue.disconnect()
