"""Durable pipeline readiness, replay, lease, and finalizer recovery contracts.

The production coordinator API is intentionally kept to the smallest seam needed
by these tests; pipeline state and outputs must be persisted by the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.transcription.processing_pipeline import ProcessingPipeline


REVISION_ID = "revision-synthetic-1"
RECORDING_ID = "recording-synthetic-1"


@pytest.fixture

def pipeline(session_factory: Any) -> tuple[ProcessingPipeline, AsyncMock, AsyncMock, AsyncMock]:
    """Use real database persistence; only provider and media I/O are external."""
    transcription = AsyncMock(return_value={"text": "synthetic transcript"})
    diarization = AsyncMock(return_value={"speakers": ["speaker-synthetic-1"]})
    excerpt_validator = AsyncMock(
        return_value={"speaker-synthetic-1": "excerpt-synthetic-1"}
    )
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
