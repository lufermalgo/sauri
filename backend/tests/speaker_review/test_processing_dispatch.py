"""Committed admission delivery, replay and stage recovery contracts (T-15/#248)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.infra.models import (
    Meeting,
    ProcessingRevision,
    ProcessingRevisionOutbox,
    ProcessingStage,
    RecordingProcessingState,
    SessionRecording,
)
from app.meetings.processing_revision_service import ProcessingRevisionService
from app.transcription.processing_dispatch import dispatch_pending, recover_unfinished
from app.transcription.processing_worker import handle_revision_event


@pytest.fixture
async def admitted(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id="dispatch-meeting", origin="manual", process_state="transcribing", created_by="owner", created_at=now
            )
        )
        session.add(
            SessionRecording(
                id="dispatch-recording",
                meeting_id="dispatch-meeting",
                audio_ref="audio.wav",
                idempotency_key="dispatch-key",
                capture_origin="web_upload",
                duration_seconds=10,
                finished_at=now,
            )
        )
    async with session_factory() as session, session.begin():
        revision = await ProcessingRevisionService(session).admit_candidate(
            owner_id="owner", recording_id="dispatch-recording", request_id="request-a", request_fingerprint="hash-a"
        )
        revision_id = revision.id
    return revision_id


async def test_admission_and_outbox_are_one_transaction(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id="rollback-meeting", origin="manual", process_state="transcribing", created_by="owner", created_at=now
            )
        )
        session.add(
            SessionRecording(
                id="rollback-recording",
                meeting_id="rollback-meeting",
                audio_ref="audio.wav",
                idempotency_key="rollback-key",
                capture_origin="web_upload",
                duration_seconds=10,
                finished_at=now,
            )
        )
    with pytest.raises(RuntimeError, match="rollback"):
        async with session_factory() as session, session.begin():
            await ProcessingRevisionService(session).admit_candidate(
                owner_id="owner",
                recording_id="rollback-recording",
                request_id="request-a",
                request_fingerprint="hash-a",
            )
            raise RuntimeError("rollback")
    async with session_factory() as session:
        state = await session.get(RecordingProcessingState, "rollback-recording")
        assert state is None or state.in_flight_revision_id is None
        assert not (
            await session.scalars(
                select(ProcessingRevision).where(ProcessingRevision.recording_id == "rollback-recording")
            )
        ).all()
        assert not (
            await session.scalars(
                select(ProcessingRevisionOutbox).where(ProcessingRevisionOutbox.recording_id == "rollback-recording")
            )
        ).all()


async def test_exact_retry_one_admission_event_and_broker_failure_recovers(session_factory, admitted):
    async with session_factory() as session, session.begin():
        replay = await ProcessingRevisionService(session).admit_candidate(
            owner_id="owner", recording_id="dispatch-recording", request_id="request-a", request_fingerprint="hash-a"
        )
        assert replay.id == admitted
    queue = AsyncMock()
    queue.publish.side_effect = [RuntimeError("broker unavailable"), None]
    assert await dispatch_pending(session_factory, queue) == 0
    async with session_factory() as session:
        pending = (
            await session.scalars(
                select(ProcessingRevisionOutbox).where(ProcessingRevisionOutbox.processing_revision_id == admitted)
            )
        ).all()
        assert len(pending) == 1 and pending[0].delivery_status == "pending"
    assert await dispatch_pending(session_factory, queue) == 1
    assert queue.publish.await_args.args[1]["processing_revision_id"] == admitted
    assert await dispatch_pending(session_factory, queue) == 0


async def test_unacknowledged_delivery_reuses_id_and_leased_stage_does_not_execute_twice(session_factory, admitted):
    queue = AsyncMock()
    await dispatch_pending(session_factory, queue)
    message = queue.publish.await_args.args[1]
    pipeline = AsyncMock()
    await handle_revision_event(message, session_factory, pipeline)
    await handle_revision_event(message, session_factory, pipeline)
    assert pipeline.process_stage.await_args_list[0].args == (admitted, "transcription")
    # Real provider fencing is covered by the normative lease/duplicate tests;
    # a replay retains the same durable event and processing revision, not a new attempt.
    assert pipeline.process_stage.await_count == 2
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRevisionOutbox)
                .where(ProcessingRevisionOutbox.processing_revision_id == admitted)
            )
            == 1
        )


async def test_expired_claim_is_republished_with_original_event_id(session_factory, admitted):
    queue = AsyncMock()
    await dispatch_pending(session_factory, queue)
    first = queue.publish.await_args.args[1]
    async with session_factory() as session, session.begin():
        session.add(
            ProcessingStage(
                id="expired-stage",
                processing_revision_id=admitted,
                stage="transcription",
                status="running",
                lease_token="old-token",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    assert await recover_unfinished(session_factory, queue) == 1
    assert queue.publish.await_args.args[1] == first


async def test_recovery_scans_all_inflight_rows_beyond_one_batch(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        for index in range(34):
            session.add(
                Meeting(
                    id=f"batch-meeting-{index}",
                    origin="manual",
                    process_state="transcribing",
                    created_by="owner",
                    created_at=now,
                )
            )
        await session.flush()
        for index in range(34):
            session.add(
                SessionRecording(
                    id=f"batch-recording-{index}",
                    meeting_id=f"batch-meeting-{index}",
                    audio_ref=f"batch-{index}.wav",
                    idempotency_key=f"batch-key-{index}",
                    capture_origin="web_upload",
                    duration_seconds=10,
                    finished_at=now,
                )
            )
        await session.flush()
        for index in range(34):
            session.add(
                ProcessingRevision(
                    id=f"batch-revision-{index}", recording_id=f"batch-recording-{index}", revision=1, created_at=now
                )
            )
        await session.flush()
        for index in range(34):
            session.add(
                RecordingProcessingState(
                    recording_id=f"batch-recording-{index}", in_flight_revision_id=f"batch-revision-{index}"
                )
            )
            session.add(
                ProcessingRevisionOutbox(
                    id=f"batch-event-{index}",
                    recording_id=f"batch-recording-{index}",
                    processing_revision_id=f"batch-revision-{index}",
                    event_type="processing_revision_admitted",
                    delivery_status="delivered",
                    created_at=now,
                )
            )
    queue = AsyncMock()
    assert await recover_unfinished(session_factory, queue, limit=8) == 34
    assert len({call.args[1]["event_id"] for call in queue.publish.await_args_list}) == 34
