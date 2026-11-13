"""T-17: production ingestion admits exactly one durable candidate and outbox event."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    ProcessingRevision,
    ProcessingRevisionOutbox,
    RecordingProcessingState,
    SpeakerReview,
    SpeakerReviewItem,
)
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion
from app.meetings.processing_revision_service import ProcessingRevisionService


def _data() -> IngestionData:
    return IngestionData(
        meeting_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        video_presence="absent",
        duration_seconds=10,
    )


@pytest.mark.asyncio
async def test_ingestion_admission_replay_and_conflict_share_upload_transaction(
    db_session: AsyncSession,
) -> None:
    data = _data()
    recording, is_new = await process_ingestion(
        db_session, data, "synthetic://audio", None, "synthetic-owner", "sha256:content-a"
    )
    assert is_new
    revision = (await db_session.scalars(select(ProcessingRevision))).one()
    assert revision.recording_id == recording.id
    assert revision.revision == 1
    assert revision.request_fingerprint == "sha256:content-a"
    state = await db_session.get(RecordingProcessingState, recording.id)
    assert state is not None
    assert state.in_flight_revision_id == revision.id
    assert state.active_processing_revision_id is None
    event = (await db_session.scalars(select(ProcessingRevisionOutbox))).one()
    assert event.processing_revision_id == revision.id
    assert event.event_type == "processing_revision_admitted"
    assert event.delivery_status == "pending"

    replay, replay_is_new = await process_ingestion(
        db_session, data, "synthetic://audio", None, "synthetic-owner", "sha256:content-a"
    )
    assert replay.id == recording.id and not replay_is_new
    assert (await db_session.scalars(select(ProcessingRevisionOutbox))).all() == [event]
    assert (await db_session.scalars(select(ProcessingRevision))).all() == [revision]

    with pytest.raises(ValueError, match="fingerprint conflict"):
        await ProcessingRevisionService(db_session).admit_candidate(
            owner_id="synthetic-owner",
            recording_id=recording.id,
            request_id=data.idempotency_key,
            request_fingerprint="sha256:content-b",
        )
    assert (await db_session.scalars(select(ProcessingRevisionOutbox))).all() == [event]
    assert state.in_flight_revision_id == revision.id


@pytest.mark.asyncio
async def test_ingestion_admission_rollback_discards_revision_and_event(
    db_session: AsyncSession,
) -> None:
    await process_ingestion(db_session, _data(), "synthetic://audio", None, "synthetic-owner")
    await db_session.rollback()
    assert (await db_session.scalars(select(ProcessingRevision))).all() == []
    assert (await db_session.scalars(select(ProcessingRevisionOutbox))).all() == []
    assert (await db_session.scalars(select(RecordingProcessingState))).all() == []


@pytest.mark.asyncio
async def test_complete_active_revision_remains_visible_while_next_candidate_is_in_flight(
    db_session: AsyncSession,
) -> None:
    data = _data()
    recording, _ = await process_ingestion(
        db_session, data, "synthetic://audio", None, "synthetic-owner", "sha256:content-a"
    )
    first = (await db_session.scalars(select(ProcessingRevision))).one()
    state = await db_session.get(RecordingProcessingState, recording.id)
    assert state is not None
    state.active_processing_revision_id = first.id
    state.in_flight_revision_id = None
    review = SpeakerReview(
        id=str(uuid.uuid4()),
        meeting_id=data.meeting_id,
        processing_revision=1,
        status="complete",
        created_at=datetime.now(UTC),
    )
    db_session.add(review)
    db_session.add(
        SpeakerReviewItem(
            id=str(uuid.uuid4()),
            review_id=review.id,
            speaker_key="speaker-1",
            current_label="Speaker 1",
            attribution_state="uncertain",
            disposition="confirmed",
            version=2,
        )
    )
    await db_session.flush()
    service = ProcessingRevisionService(db_session)
    candidate = await service.admit_candidate(
        owner_id="synthetic-owner",
        recording_id=recording.id,
        request_id="next-request",
        request_fingerprint="sha256:content-b",
    )
    assert candidate.revision == 2
    assert candidate.admitted_active_revision_id == first.id
    assert state.active_processing_revision_id == first.id
    assert state.in_flight_revision_id == candidate.id
    assert len((await db_session.scalars(select(ProcessingRevisionOutbox))).all()) == 2

    with pytest.raises(ValueError, match="in flight"):
        await service.admit_candidate(
            owner_id="synthetic-owner",
            recording_id=recording.id,
            request_id="third-request",
            request_fingerprint="sha256:content-c",
        )
    assert state.active_processing_revision_id == first.id
    assert state.in_flight_revision_id == candidate.id
    assert len((await db_session.scalars(select(ProcessingRevisionOutbox))).all()) == 2
