from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    SessionRecording,
    SpeechTurn,
    Transcript,
)
from app.infra.processing_claims import claim_worker_generation, verify_worker_generation
from app.transcription.asr_engine import ASRCapabilities, TranscriptionResult, TranscriptionSegment
from app.transcription.worker import _process_transcription


async def _seed(session_factory: async_sessionmaker[AsyncSession], *, generation: int = 4,
                claim_id: str | None = None, claim_kind: str | None = None,
                expires_at: datetime | None = None, include_claim: bool = True
                ) -> tuple[str, str, str]:
    meeting_id, recording_id, owner_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link="https://meet.google.com/synthetic", origin="link",
            calendar_invite_id=None, scheduled_start_time=None, process_state="transcribing",
            failure_cause=None, created_by=owner_id, created_at=datetime.now(UTC),
        ))
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
            capture_origin="chrome_extension", audio_ref="synthetic/audio", video_ref=None,
            duration_seconds=1, interrupted=False, expires_at=None, finished_at=datetime.now(UTC),
        ))
        if include_claim:
            session.add(MeetingProcessingClaim(
                meeting_id=meeting_id, generation=generation, claim_id=claim_id,
                claim_kind=claim_kind, claim_expires_at=expires_at,
            ))
    return meeting_id, recording_id, owner_id


@pytest.mark.asyncio
async def test_stale_generation_is_acknowledged_without_engine_or_writes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment(text="synthetic", start_ms=0, end_ms=1)],
        language="es-CO", supports_turns=True,
    )
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "audio_ref": "untrusted", "generation": 3, "job_id": str(uuid.uuid4()),
        }, session_factory)

    engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        assert (await session.execute(select(Transcript))).scalars().all() == []
        assert (await session.execute(select(SpeechTurn))).scalars().all() == []
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "transcribing"


@pytest.mark.asyncio
async def test_worker_claim_first_consumes_generation_and_duplicate_does_not_reinvoke(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())
    message = {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        "audio_ref": "untrusted", "generation": 4, "job_id": job_id,
    }
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(segments=[], language="es-CO", supports_turns=True)
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(message, session_factory)
        await _process_transcription(message, session_factory)

    assert engine.transcribe.await_count == 1
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == job_id
        assert claim.claim_kind == "transcription"


@pytest.mark.asyncio
async def test_successful_transcription_publishes_next_monotonic_generation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment(text="synthetic", start_ms=0, end_ms=1)],
        language="es-CO", supports_turns=True,
    )
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))
    queue = AsyncMock()
    message = {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        "audio_ref": "untrusted", "generation": 4, "job_id": str(uuid.uuid4()),
    }

    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(message, session_factory, queue)

    queue.publish.assert_awaited_once()
    topic, diarization_job = queue.publish.await_args.args
    assert topic == "diarize"
    assert diarization_job["generation"] == 5
    assert uuid.UUID(diarization_job["job_id"])
    assert diarization_job["meeting_id"] == meeting_id
    assert diarization_job["owner_id"] == owner_id
    assert diarization_job["recording_id"] == recording_id
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.generation == 5
        assert claim.claim_id is None and claim.claim_kind is None


@pytest.mark.asyncio
async def test_expired_claim_is_uncertain_and_never_taken_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old_claim = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=old_claim, claim_kind="recovery",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    engine = AsyncMock()
    message = {
        "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
        "audio_ref": "untrusted", "generation": 4, "job_id": str(uuid.uuid4()),
    }
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription(message, session_factory)
    engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == old_claim
        assert claim.claim_kind == "recovery"


@pytest.mark.asyncio
async def test_recovery_claim_first_blocks_delayed_transcription_delivery(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recovery_operation_id = str(uuid.uuid4())
    meeting_id, recording_id, owner_id = await _seed(
        session_factory, claim_id=recovery_operation_id, claim_kind="recovery"
    )
    engine = AsyncMock()
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "audio_ref": "untrusted", "generation": 4, "job_id": str(uuid.uuid4()),
        }, session_factory)
    engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None and claim.claim_id == recovery_operation_id
        assert claim.claim_kind == "recovery"
        assert (await session.execute(select(Transcript))).scalars().all() == []


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
            idempotency_key="a" * 64, processing_generation=4, status="dispatch_pending",
            reason_code=None, preservation_snapshot_digest=None, preservation_counts={},
            created_at=now, updated_at=now,
        ))

    engine = AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(
        segments=[TranscriptionSegment(text="sentinel", start_ms=0, end_ms=1)],
        language="es-CO", supports_turns=True,
    )
    engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "audio_ref": "untrusted", "generation": 4, "job_id": str(uuid.uuid4()),
            "operation_id": operation_id,
        }, session_factory)

    engine.transcribe.assert_not_awaited()
    async with session_factory() as session:
        assert await session.get(MeetingProcessingClaim, meeting_id) is None
        assert not await claim_worker_generation(
            session, meeting_id=meeting_id, generation=4, job_id="retry", kind="transcription",
            operation_id=operation_id,
        )
        assert not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=4, job_id="retry", kind="transcription",
            operation_id=operation_id,
        )
        assert (await session.execute(select(Transcript))).scalars().all() == []
        assert (await session.execute(select(SpeechTurn))).scalars().all() == []
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "transcribing"


@pytest.mark.asyncio
async def test_legacy_delivery_for_claim_tracked_meeting_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, recording_id, owner_id = await _seed(session_factory)
    engine = AsyncMock()
    with patch("app.transcription.worker.create_asr_engine", return_value=engine):
        await _process_transcription({
            "meeting_id": meeting_id, "owner_id": owner_id, "recording_id": recording_id,
            "audio_ref": "untrusted",
        }, session_factory)
    engine.transcribe.assert_not_awaited()
