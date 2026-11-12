from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.diarization_engine import DiarizationCapabilities, DiarizationResult
from app.diarization.worker import _process_diarization
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    SessionRecording,
    SpeechTurn,
    Transcript,
)
from app.infra.processing_claims import claim_worker_generation, verify_worker_generation


def _engine() -> AsyncMock:
    engine = AsyncMock()
    engine.diarize.return_value = DiarizationResult(segments=[], speaker_count=0)
    engine.capabilities = MagicMock(
        return_value=DiarizationCapabilities(is_local=True, provider_name="synthetic")
    )
    return engine


async def _seed(session_factory: async_sessionmaker[AsyncSession], *, generation: int = 8,
                claim_id: str | None = None, claim_kind: str | None = None,
                expires_at: datetime | None = None, include_claim: bool = True
                ) -> tuple[str, str, str]:
    meeting_id, recording_id, owner_id, transcript_id = (
        str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    )
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link="https://meet.google.com/synthetic", origin="link",
            calendar_invite_id=None, scheduled_start_time=None, process_state="completed",
            failure_cause=None, created_by=owner_id, created_at=datetime.now(UTC),
        ))
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
            capture_origin="chrome_extension", audio_ref="synthetic/audio", video_ref=None,
            duration_seconds=1, interrupted=False, expires_at=None, finished_at=datetime.now(UTC),
        ))
        session.add(Transcript(
            id=transcript_id, meeting_id=meeting_id, language="es-CO", provider="local",
            supports_turns=True, expires_at=None, created_at=datetime.now(UTC),
        ))
        session.add(SpeechTurn(
            id=str(uuid.uuid4()), transcript_id=transcript_id, text="synthetic", start_ms=0,
            end_ms=1, sequence=1,
        ))
        if include_claim:
            session.add(MeetingProcessingClaim(
                meeting_id=meeting_id, generation=generation, claim_id=claim_id,
                claim_kind=claim_kind, claim_expires_at=expires_at,
            ))
    return meeting_id, recording_id, owner_id


@pytest.mark.asyncio
async def test_stale_generation_is_acknowledged_without_engine_or_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = _engine()
    engine.diarize.return_value = DiarizationResult(segments=[], speaker_count=0)

    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "generation": 7, "job_id": str(uuid.uuid4()),
        }, session_factory)

    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        assert (await session.execute(select(Diarization))).scalars().all() == []


@pytest.mark.asyncio
async def test_worker_claim_first_consumes_generation_and_duplicate_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    message = {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        "generation": 8, "job_id": str(uuid.uuid4()),
    }
    engine = _engine()
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(message, session_factory)
        await _process_diarization(message, session_factory)

    assert engine.diarize.await_count == 1
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == message["job_id"]
        assert claim.claim_kind == "diarization"
        assert len((await session.execute(select(Diarization))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_recovery_claim_wins_interleaving_and_worker_cannot_take_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recovery_claim_id = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=recovery_claim_id, claim_kind="recovery",
    )
    engine = _engine()
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "generation": 8, "job_id": str(uuid.uuid4()),
        }, session_factory)
    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == recovery_claim_id
        assert claim.claim_kind == "recovery"


@pytest.mark.asyncio
async def test_recovery_delivery_without_durable_claim_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory, include_claim=False)
    operation_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(MeetingRecoveryOperation(
            id=operation_id, meeting_id=meeting_id, actor_id=owner_id,
            idempotency_key="b" * 64, processing_generation=8, status="dispatch_pending",
            reason_code=None, preservation_snapshot_digest=None, preservation_counts={},
            created_at=now, updated_at=now,
        ))

    engine = _engine()
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "generation": 8, "job_id": str(uuid.uuid4()), "operation_id": operation_id,
        }, session_factory)

    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        assert await session.get(MeetingProcessingClaim, meeting_id) is None
        assert not await claim_worker_generation(
            session, meeting_id=meeting_id, generation=8, job_id="retry", kind="diarization",
            operation_id=operation_id,
        )
        assert not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=8, job_id="retry", kind="diarization",
            operation_id=operation_id,
        )
        assert (await session.execute(select(Diarization))).scalars().all() == []


@pytest.mark.asyncio
async def test_expired_claim_and_worker_restart_do_not_reset_or_reclaim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    previous_claim = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=previous_claim, claim_kind="diarization",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    engine = _engine()
    message = {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        "generation": 8, "job_id": str(uuid.uuid4()),
    }
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(message, session_factory)
        await _process_diarization(message, session_factory)
    engine.diarize.assert_not_awaited()
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == previous_claim
        assert claim.claim_kind == "diarization"
        assert (await session.execute(select(Diarization))).scalars().all() == []


@pytest.mark.asyncio
async def test_legacy_delivery_for_claim_tracked_meeting_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = _engine()
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        }, session_factory)
    engine.diarize.assert_not_awaited()
