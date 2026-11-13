"""T11 #650: synthetic, behavioral regression for legacy backfill."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.diarization.reprocess_legacy import reprocess_legacy
from app.infra.models import Diarization, Meeting, SessionRecording, Transcript


async def seed(factory, *, recording=True, audio_ref="synthetic/exact.webm", recording_expired=False,
               transcript_expired=False):
    now = datetime.now(UTC)
    meeting_id, transcript_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(Meeting(id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij",
                            origin="link", process_state="completed", created_by="synthetic-user",
                            created_at=now))
        session.add(Transcript(id=transcript_id, meeting_id=meeting_id, provider="synthetic",
                               supports_turns=True, created_at=now,
                               expires_at=now - timedelta(seconds=1) if transcript_expired else None))
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
    if expired:
        store.inspect.assert_not_awaited()
    await reprocess_legacy(session_factory, store, queue)
    assert len(await attempts(session_factory, meeting_id)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_recording", "empty_reference", "expired_transcript", "permission", "timeout"])
async def test_unknown_or_ineligible_never_infers_terminal(session_factory, case):
    meeting_id = await seed(session_factory, recording=case != "missing_recording",
                            audio_ref="" if case == "empty_reference" else "synthetic/exact.webm",
                            transcript_expired=case == "expired_transcript")
    store, queue = AsyncMock(), AsyncMock()
    store.inspect.side_effect = PermissionError("denied") if case == "permission" else TimeoutError("retry")
    if case in {"permission", "timeout"}:
        with pytest.raises((PermissionError, TimeoutError)):
            await reprocess_legacy(session_factory, store, queue)
    else:
        await reprocess_legacy(session_factory, store, queue)
        store.inspect.assert_not_awaited()
    assert len(await attempts(session_factory, meeting_id)) == 1
    queue.publish.assert_not_awaited()
