"""T11 #650: synthetic, behavioral regression for legacy backfill."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.diarization.diarization_engine import DiarizationCapabilities, DiarizationResult
from app.diarization.reprocess_legacy import reprocess_legacy
from app.diarization.worker import _process_diarization
from app.infra.database import Base
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    Transcript,
)


async def seed(factory, *, recording=True, audio_ref="synthetic/exact.webm", recording_expired=False,
               transcript_expired=False):
    now = datetime.now(UTC)
    meeting_id, transcript_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(Meeting(id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij",
                            origin="link", process_state="completed", created_by="synthetic-user",
                            created_at=now))
        await session.flush()
        session.add(Transcript(id=transcript_id, meeting_id=meeting_id, provider="synthetic",
                               supports_turns=True, created_at=now,
                               expires_at=now - timedelta(seconds=1) if transcript_expired else None))
        await session.flush()
        if recording:
            session.add(SessionRecording(id=str(uuid.uuid4()), meeting_id=meeting_id,
                                         idempotency_key=str(uuid.uuid4()), capture_origin="chrome_extension",
                                         audio_ref=audio_ref, duration_seconds=3, interrupted=False,
                                         finished_at=now,
                                         expires_at=now - timedelta(seconds=1) if recording_expired else None))
        session.add(Diarization(id=str(uuid.uuid4()), meeting_id=meeting_id,
                                transcript_id=transcript_id, is_legacy=True, provider="synthetic",
                                speaker_count=0, processing_revision=1, diarization_state="completed",
                                created_at=now, updated_at=now))
    return meeting_id


async def attempts(factory, meeting_id):
    async with factory() as session:
        return (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id)
                                      .order_by(Diarization.processing_revision))).all()


@pytest.mark.asyncio
async def test_exact_audio_and_replay_after_committed_reservation(session_factory):
    meeting_id = await seed(session_factory)
    store, queue = AsyncMock(), AsyncMock()
    store.inspect.return_value = "available"
    queue.publish.side_effect = RuntimeError("broker down")
    with pytest.raises(RuntimeError, match="broker down"):
        await reprocess_legacy(session_factory, store, queue)
    assert [(a.processing_revision, a.diarization_state) for a in await attempts(session_factory, meeting_id)] == [
        (1, "completed"), (2, "pending")]
    queue.publish.side_effect = None
    await reprocess_legacy(session_factory, store, queue)
    await reprocess_legacy(session_factory, store, queue)
    assert len(await attempts(session_factory, meeting_id)) == 2
    store.inspect.assert_any_await("synthetic/exact.webm")
    queue.publish.assert_awaited_with("diarize", {"meeting_id": meeting_id, "processing_revision": 2})


@pytest.mark.asyncio
@pytest.mark.parametrize(("expired", "availability"), [(True, "available"), (False, "missing")])
async def test_authoritative_audio_unavailable_is_terminal(session_factory, expired, availability):
    meeting_id = await seed(session_factory, recording_expired=expired)
    store, queue = AsyncMock(), AsyncMock()
    store.inspect.return_value = availability
    await reprocess_legacy(session_factory, store, queue)
    rows = await attempts(session_factory, meeting_id)
    assert [(row.processing_revision, row.diarization_state, row.failure_cause) for row in rows] == [
        (1, "completed", None), (2, "not_reconstructible", "audio_unavailable")]
    queue.publish.assert_not_awaited()
    async with session_factory() as session:
        for model in (Speaker, SpeakerAssignment, SpeakerReview):
            assert (await session.scalars(select(model))).all() == []
    if expired:
        store.inspect.assert_not_awaited()
    await reprocess_legacy(session_factory, store, queue)
    assert len(await attempts(session_factory, meeting_id)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "missing_recording", "empty_reference", "expired_transcript", "permission", "timeout", "invalid",
])
async def test_unknown_or_ineligible_never_infers_terminal(session_factory, case):
    meeting_id = await seed(session_factory, recording=case != "missing_recording",
                            audio_ref="" if case == "empty_reference" else "synthetic/exact.webm",
                            transcript_expired=case == "expired_transcript")
    store, queue = AsyncMock(), AsyncMock()
    store.inspect.side_effect = PermissionError("denied") if case == "permission" else (
        TimeoutError("retry") if case == "timeout" else None
    )
    store.inspect.return_value = "indeterminate"
    if case in {"permission", "timeout", "invalid"}:
        with pytest.raises((PermissionError, TimeoutError, ValueError)):
            await reprocess_legacy(session_factory, store, queue)
    else:
        await reprocess_legacy(session_factory, store, queue)
        store.inspect.assert_not_awaited()
    assert len(await attempts(session_factory, meeting_id)) == 1
    queue.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["available", "missing", "expired", "permission", "transcript_expired"])
async def test_reserved_worker_rechecks_exact_object_before_engine(session_factory, outcome):
    meeting_id = await seed(session_factory)
    store, queue = AsyncMock(), AsyncMock()
    store.inspect.return_value = "available"
    await reprocess_legacy(session_factory, store, queue)
    async with session_factory() as session, session.begin():
        if outcome == "expired":
            recording = await session.scalar(select(SessionRecording).where(
                SessionRecording.meeting_id == meeting_id))
            recording.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if outcome == "transcript_expired":
            transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))
            transcript.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    store.inspect.return_value = "missing" if outcome == "missing" else "available"
    if outcome == "permission":
        store.inspect.side_effect = PermissionError("denied")
    engine = MagicMock()
    engine.diarize = AsyncMock(return_value=DiarizationResult(segments=[], speaker_count=0))
    engine.capabilities.return_value = DiarizationCapabilities(is_local=True, provider_name="synthetic")
    with patch("app.diarization.worker.create_object_store", return_value=store), patch(
        "app.diarization.worker.create_diarization_engine", return_value=engine
    ):
        if outcome == "permission":
            with pytest.raises(PermissionError):
                await _process_diarization({"meeting_id": meeting_id, "processing_revision": 2}, session_factory)
        else:
            await _process_diarization({"meeting_id": meeting_id, "processing_revision": 2}, session_factory)
    rows = await attempts(session_factory, meeting_id)
    if outcome == "available":
        assert rows[-1].diarization_state == "completed"
        engine.diarize.assert_awaited_once()
        assert engine.diarize.await_args.args[0] == "synthetic/exact.webm"
        await _process_diarization({"meeting_id": meeting_id, "processing_revision": 2}, session_factory)
        assert engine.diarize.await_count == 1
    else:
        engine.diarize.assert_not_awaited()
        assert rows[-1].diarization_state == (
            "pending" if outcome in {"permission", "transcript_expired"} else "not_reconstructible"
        )
        assert rows[-1].failure_cause == (
            None if outcome in {"permission", "transcript_expired"} else "audio_unavailable"
        )
        if outcome in {"expired", "transcript_expired"}:
            assert store.inspect.await_count == 1  # Only the prior backfill inspected it.


@pytest.mark.asyncio
async def test_concurrent_real_postgres_backfill_reserves_one_revision():
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated PostgreSQL QA database required")
    assert url.startswith("postgresql+asyncpg://") and "sauri_qa" in url
    engine = create_async_engine(url)
    assert engine.dialect.name == "postgresql"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        meeting_id = await seed(factory)
        store, queue = AsyncMock(), AsyncMock()
        store.inspect.return_value = "available"
        await asyncio.wait_for(asyncio.gather(
            reprocess_legacy(factory, store, queue),
            reprocess_legacy(factory, store, queue),
        ), timeout=10)
        assert [(a.processing_revision, a.diarization_state) for a in await attempts(factory, meeting_id)] == [
            (1, "completed"), (2, "pending")]
        assert queue.publish.await_count == 2  # Redelivery is safe; single revision.
        for call in queue.publish.await_args_list:
            assert call.args == ("diarize", {"meeting_id": meeting_id, "processing_revision": 2})
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
