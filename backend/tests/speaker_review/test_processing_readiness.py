"""Durable pipeline readiness, replay, lease, and finalizer recovery contracts.

The production coordinator API is intentionally kept to the smallest seam needed
by these tests; pipeline state and outputs must be persisted by the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.infra.models import (
    Diarization,
    Meeting,
    ProcessingRevision,
    ProcessingRevisionOutbox,
    RecordingProcessingState,
    SessionRecording,
    SpeakerAssignment,
    Transcript,
)
from app.transcription.processing_pipeline import ProcessingPipeline

REVISION_ID = "revision-synthetic-1"
RECORDING_ID = "recording-synthetic-1"


@pytest.fixture
async def pipeline(session_factory: Any) -> tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock]:
    """Persist a real admitted recording/revision; mock only external I/O."""
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id="meeting-synthetic-1",
                origin="manual",
                process_state="transcribing",
                created_by="owner-synthetic-1",
                created_at=now,
            )
        )
        session.add(
            SessionRecording(
                id=RECORDING_ID,
                meeting_id="meeting-synthetic-1",
                idempotency_key="recording-synthetic-key",
                capture_origin="web_upload",
                audio_ref="synthetic/audio.wav",
                duration_seconds=10,
                finished_at=now,
            )
        )
    async with session_factory() as session, session.begin():
        session.add(
            ProcessingRevision(
                id=REVISION_ID,
                recording_id=RECORDING_ID,
                revision=1,
                request_id="synthetic-request-1",
                request_fingerprint="synthetic-fingerprint",
                created_at=now,
            )
        )
        session.add(RecordingProcessingState(recording_id=RECORDING_ID, in_flight_revision_id=REVISION_ID))
    transcription = AsyncMock(
        return_value={
            "text": "synthetic transcript",
            "segments": [{"text": "synthetic transcript", "start_ms": 0, "end_ms": 1000}],
        }
    )
    diarization = AsyncMock(
        return_value={
            "speakers": ["speaker-synthetic-1"],
            "segments": [{"raw_label": "speaker-synthetic-1", "start_ms": 0, "end_ms": 1000}],
        }
    )
    excerpt_validator = AsyncMock(return_value={"speaker-synthetic-1": "excerpt-synthetic-1"})
    return (
        ProcessingPipeline(
            session_factory,
            transcription_provider=transcription,
            diarization_provider=diarization,
            excerpt_validator=excerpt_validator,
        ),
        transcription,
        diarization,
        excerpt_validator,
    )


async def test_review_is_hidden_until_all_revision_outputs_are_validated(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, _, _, _ = pipeline

    await coordinator.process_stage(REVISION_ID, "transcription")
    assert await coordinator.get_review(RECORDING_ID) is None

    # An early/replayed finalizer must not publish a review without diarization.
    await coordinator.finalize(REVISION_ID)
    assert await coordinator.get_review(RECORDING_ID) is None

    await coordinator.process_stage(REVISION_ID, "diarization")
    assert await coordinator.get_review(RECORDING_ID) is None

    await coordinator.finalize(REVISION_ID)
    review = await coordinator.get_review(RECORDING_ID)
    assert review is not None
    assert review["processing_revision_id"] == REVISION_ID
    assert review["speaker_keys"] == ["speaker-synthetic-1"]
    assert review["excerpts"] == {"speaker-synthetic-1": "excerpt-synthetic-1"}


async def test_duplicate_stage_and_finalizer_delivery_replay_durable_output_without_provider_rerun(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, transcription, diarization, _ = pipeline

    first_transcript = await coordinator.process_stage(REVISION_ID, "transcription")
    replayed_transcript = await coordinator.process_stage(REVISION_ID, "transcription")
    await coordinator.process_stage(REVISION_ID, "diarization")
    first_review = await coordinator.finalize(REVISION_ID)
    replayed_review = await coordinator.finalize(REVISION_ID)

    assert replayed_transcript == first_transcript
    assert first_review == replayed_review
    assert transcription.await_count == 1
    assert diarization.await_count == 1
    assert await coordinator.count_stage_outputs(REVISION_ID) == 2
    assert await coordinator.count_reviews(RECORDING_ID, REVISION_ID) == 1


async def test_unexpired_stage_lease_blocks_duplicate_provider_execution(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, transcription, _, _ = pipeline

    claim = await coordinator.claim_stage(REVISION_ID, "transcription")
    assert claim.acquired is True
    duplicate = await coordinator.claim_stage(REVISION_ID, "transcription")

    assert duplicate.acquired is False
    await coordinator.process_stage(REVISION_ID, "transcription")
    assert transcription.await_count == 0


async def test_expired_stage_lease_permits_recovery(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, transcription, _, _ = pipeline

    await coordinator.claim_stage(
        REVISION_ID,
        "transcription",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    recovered = await coordinator.process_stage(REVISION_ID, "transcription")

    assert recovered["text"] == "synthetic transcript"
    assert transcription.await_count == 1


async def test_stage_output_completion_and_outbox_event_roll_back_atomically(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, _, _, _ = pipeline

    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        await coordinator.process_stage(
            REVISION_ID,
            "transcription",
            before_commit=AsyncMock(side_effect=RuntimeError("synthetic transaction failure")),
        )

    assert await coordinator.count_stage_outputs(REVISION_ID) == 0
    assert await coordinator.is_stage_complete(REVISION_ID, "transcription") is False
    assert await coordinator.count_outbox_events(REVISION_ID, "transcription") == 0


async def test_finalizer_recovers_from_persisted_stages_without_rerunning_providers(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    coordinator, transcription, diarization, _ = pipeline
    await coordinator.process_stage(REVISION_ID, "transcription")
    await coordinator.process_stage(REVISION_ID, "diarization")

    with pytest.raises(RuntimeError, match="synthetic finalizer failure"):
        await coordinator.finalize(
            REVISION_ID,
            before_commit=AsyncMock(side_effect=RuntimeError("synthetic finalizer failure")),
        )
    assert await coordinator.get_review(RECORDING_ID) is None

    recovered = await coordinator.finalize(REVISION_ID)

    assert recovered is not None
    assert await coordinator.get_review(RECORDING_ID) == recovered
    assert transcription.await_count == 1
    assert diarization.await_count == 1


async def test_stage_output_is_real_revision_scoped_transcript_assignment_and_event(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
    session_factory: Any,
) -> None:
    coordinator, _, _, _ = pipeline
    await coordinator.process_stage(REVISION_ID, "transcription")
    await coordinator.process_stage(REVISION_ID, "diarization")
    async with session_factory() as session:
        transcript = await session.scalar(select(Transcript).where(Transcript.processing_revision_id == REVISION_ID))
        diarization = await session.scalar(select(Diarization).where(Diarization.processing_revision_id == REVISION_ID))
        assert transcript is not None and diarization is not None
        assert diarization.transcript_id == transcript.id
        assignments = (
            await session.scalars(select(SpeakerAssignment).where(SpeakerAssignment.diarization_id == diarization.id))
        ).all()
        assert len(assignments) == 1 and assignments[0].overlap_ms == 1000
        events = (
            await session.scalars(
                select(ProcessingRevisionOutbox).where(ProcessingRevisionOutbox.processing_revision_id == REVISION_ID)
            )
        ).all()
        assert {event.event_type for event in events} == {"transcription_completed", "diarization_completed"}


async def test_failed_excerpt_validation_leaves_candidate_and_stages_retryable(
    pipeline: tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock],
    session_factory: Any,
) -> None:
    coordinator, transcription, diarization, excerpt_validator = pipeline
    await coordinator.process_stage(REVISION_ID, "transcription")
    await coordinator.process_stage(REVISION_ID, "diarization")
    excerpt_validator.side_effect = ValueError("validated excerpts unavailable")
    with pytest.raises(ValueError, match="validated excerpts unavailable"):
        await coordinator.finalize(REVISION_ID)
    assert await coordinator.get_review(RECORDING_ID) is None
    async with session_factory() as session:
        state = await session.get(RecordingProcessingState, RECORDING_ID)
        meeting = await session.get(Meeting, "meeting-synthetic-1")
        assert state is not None and state.in_flight_revision_id == REVISION_ID
        assert state.active_processing_revision_id is None
        assert meeting is not None and meeting.process_state == "transcribing"
    excerpt_validator.side_effect = None
    assert await coordinator.finalize(REVISION_ID) is not None
    async with session_factory() as session:
        meeting = await session.get(Meeting, "meeting-synthetic-1")
        assert meeting is not None and meeting.process_state == "completed"
    assert transcription.await_count == diarization.await_count == 1
