"""A diarization worker that died mid-run is replaced on redelivery, and its attempt is reopened (#1166)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.diarization_engine import DiarizationResult
from app.diarization.worker import _process_diarization
from app.infra.models import Diarization, MeetingProcessingClaim, Transcript
from app.infra.processing_claims import ClaimBusy
from tests.diarization.test_recovery_worker_fence import _engine, _seed

pytestmark = pytest.mark.asyncio


def _message(meeting_id: str, recording_id: str, owner_id: str, job_id: str) -> dict[str, object]:
    return {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id, "generation": 8,
        "job_id": job_id,
    }


async def _leave_attempt_in_progress(factory: async_sessionmaker[AsyncSession], meeting_id: str) -> None:
    async with factory() as session, session.begin():
        transcript_id = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id))
        assert transcript_id is not None
        now = datetime.now(UTC)
        session.add(Diarization(
            id=str(uuid.uuid4()), meeting_id=meeting_id, transcript_id=transcript_id, processing_revision=1,
            is_legacy=False, provider=None, speaker_count=0, diarization_state="in_progress",
            created_at=now, updated_at=now,
        ))


async def test_takeover_reopens_the_attempt_the_dead_worker_left_in_progress(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dead = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=dead, claim_kind="diarization", expires_at=datetime.now(UTC) - timedelta(minutes=3),
    )
    await _leave_attempt_in_progress(session_factory, meeting_id)
    engine = _engine()

    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(_message(meeting_id, recording_id, owner_id, dead), session_factory)

    assert engine.diarize.await_count == 1
    async with session_factory() as session:
        attempts = (await session.execute(select(Diarization))).scalars().all()
        assert [a.diarization_state for a in attempts] == ["completed"]
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id not in (None, dead)


async def test_redelivery_while_the_lease_is_live_is_deferred_and_leaves_the_attempt_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    holder = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=holder, claim_kind="diarization", expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    await _leave_attempt_in_progress(session_factory, meeting_id)
    engine = _engine()

    with patch("app.diarization.worker.create_diarization_engine", return_value=engine), pytest.raises(ClaimBusy):
        await _process_diarization(_message(meeting_id, recording_id, owner_id, str(uuid.uuid4())), session_factory)

    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        attempt = await session.scalar(select(Diarization))
        assert attempt is not None and attempt.diarization_state == "in_progress"


async def test_shutdown_cancelling_a_running_diarization_releases_claim_and_reopens_the_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())
    engine = _engine()
    started = asyncio.Event()

    async def slow(*args: object, **kwargs: object) -> DiarizationResult:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("not reached")

    engine.diarize.side_effect = slow
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        task = asyncio.create_task(_process_diarization(
            _message(meeting_id, recording_id, owner_id, job_id), session_factory,
        ))
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id is None
        attempt = await session.scalar(select(Diarization))
        # Still in progress here; the next delivery reopens it under its own claim (test above).
        assert attempt is not None and attempt.diarization_state == "in_progress"

    resumed = _engine()
    with patch("app.diarization.worker.create_diarization_engine", return_value=resumed):
        await _process_diarization(_message(meeting_id, recording_id, owner_id, job_id), session_factory)
    assert resumed.diarize.await_count == 1
