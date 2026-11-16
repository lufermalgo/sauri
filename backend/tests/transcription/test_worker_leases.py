"""A restart or crash must never leave a transcription stuck: lapsed claims are taken over (#1166)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, MeetingProcessingClaim, StateHistory, Transcript
from app.infra.processing_claims import ClaimBusy
from app.transcription.asr_engine import ASRCapabilities, TranscriptionResult, TranscriptionSegment
from app.transcription.worker import _process_transcription
from tests.transcription.test_recovery_worker_fence import _seed

pytestmark = pytest.mark.asyncio


def _engine(delay_s: float = 0.0) -> AsyncMock:
    engine = AsyncMock()

    async def transcribe(*args: object, **kwargs: object) -> TranscriptionResult:
        await asyncio.sleep(delay_s)
        return TranscriptionResult(
            segments=[TranscriptionSegment(text="synthetic", start_ms=0, end_ms=1)], language="es-CO",
            supports_turns=True,
        )

    engine.transcribe.side_effect = transcribe
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))
    return engine


def _message(meeting_id: str, recording_id: str, owner_id: str, job_id: str | None = None) -> dict[str, object]:
    return {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id, "audio_ref": "untrusted",
        "generation": 4, "job_id": job_id or str(uuid.uuid4()),
    }


async def test_claim_left_without_expiry_by_an_older_worker_no_longer_strands_the_meeting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The 2026-11-16 incident: claim_id set, claim_expires_at NULL, worker recreated, delivery dropped."""
    old_job = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(session_factory, claim_id=old_job, claim_kind="transcription")
    async with session_factory() as session, session.begin():
        session.add(StateHistory(
            id=str(uuid.uuid4()), meeting_id=meeting_id, state="transcribing", failure_cause=None,
            occurred_at=datetime.now(UTC) - timedelta(hours=1),
        ))
    engine = _engine()

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(_message(meeting_id, recording_id, owner_id, old_job), session_factory)

    assert engine.transcribe.await_count == 1
    async with session_factory() as session:
        assert await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id)) is not None
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "completed"


async def test_redelivery_while_another_worker_holds_a_live_lease_is_deferred(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    holder = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=holder, claim_kind="transcription",
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    engine = _engine()

    with patch("app.transcription.worker.create_asr_engine", return_value=engine), pytest.raises(ClaimBusy):
        await _process_transcription(_message(meeting_id, recording_id, owner_id), session_factory)

    engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == holder


async def test_a_holder_that_lost_its_claim_during_the_engine_call_writes_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = _engine()
    new_holder = str(uuid.uuid4())

    async def taken_over_meanwhile(*args: object, **kwargs: object) -> TranscriptionResult:
        async with session_factory() as session, session.begin():
            claim = await session.get(MeetingProcessingClaim, meeting_id)
            assert claim is not None
            claim.claim_id = new_holder  # what a takeover after a lapsed lease does
        return TranscriptionResult(
            segments=[TranscriptionSegment(text="late", start_ms=0, end_ms=1)], language="es-CO", supports_turns=True,
        )

    engine.transcribe.side_effect = taken_over_meanwhile
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(_message(meeting_id, recording_id, owner_id), session_factory)

    async with session_factory() as session:
        assert (await session.execute(select(Transcript))).scalars().all() == []
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "transcribing"
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == new_holder  # and it did not release it from under them


async def test_an_engine_call_longer_than_the_lease_still_commits(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROCESSING_LEASE_SECONDS", "0.6")
    monkeypatch.setenv("PROCESSING_HEARTBEAT_SECONDS", "0.1")
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = _engine(delay_s=1.5)  # two and a half leases in a single call

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(_message(meeting_id, recording_id, owner_id), session_factory)

    async with session_factory() as session:
        assert await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id)) is not None


async def test_shutdown_cancelling_a_running_job_releases_the_claim_and_fails_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = _engine(delay_s=30)
    job_id = str(uuid.uuid4())

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        task = asyncio.create_task(_process_transcription(
            _message(meeting_id, recording_id, owner_id, job_id), session_factory,
        ))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if engine.transcribe.await_count:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with session_factory() as session:
            claim = await session.get(MeetingProcessingClaim, meeting_id)
            meeting = await session.get(Meeting, meeting_id)
            assert claim is not None and claim.claim_id is None and claim.claim_expires_at is None
            assert meeting is not None and meeting.process_state == "transcribing"

        # The requeued delivery resumes it straight away.
        engine.transcribe.side_effect = _engine().transcribe.side_effect
        await _process_transcription(_message(meeting_id, recording_id, owner_id, job_id), session_factory)
    async with session_factory() as session:
        assert await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id)) is not None


async def test_redelivery_after_a_crash_between_commit_and_handoff_still_publishes_diarization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The worker died after committing the transcript but before publishing it to diarization."""
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())
    message = _message(meeting_id, recording_id, owner_id, job_id)
    queue = AsyncMock()
    queue.publish.side_effect = ConnectionError("broker down")
    with patch("app.transcription.worker.create_asr_engine", return_value=_engine()), pytest.raises(ConnectionError):
        await _process_transcription(message, session_factory, queue)
    queue.publish.side_effect = None

    await _process_transcription(message, session_factory, queue)

    queue.publish.assert_awaited()
    topic, job = queue.publish.await_args.args
    assert topic == "diarize" and job["generation"] == 5 and job["meeting_id"] == meeting_id
