"""Property test for capture-origin interchangeability (Meeting_Assistant).

# Feature: meeting-capture-transcription, Property 15: Capture-origin interchangeability
Task: 13.2 — Validates: Requirements 2.1, 2.2
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SessionRecording
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion

ORIGINS = ["chrome_extension", "server_bot"]


# ---------------------------------------------------------------------------
# Property 15: Capture-origin interchangeability
# Feature: meeting-capture-transcription, Property 15: Capture-origin interchangeability
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    origin=st.sampled_from(ORIGINS),
    duration_seconds=st.integers(min_value=0, max_value=36_000),
    interrupted=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_15_pipeline_identical_regardless_of_origin(
    db_session: AsyncSession, origin: str, duration_seconds: int, interrupted: bool
) -> None:
    """The ingestion pipeline produces the same observable result (state, fields)
    regardless of whether the origin is the Chrome extension or a server bot."""
    meeting_id = str(uuid.uuid4())
    data = IngestionData(
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin=origin,
        duration_seconds=duration_seconds,
        interrupted=interrupted,
        notice_issued_at=None,
    )

    recording, is_new = await process_ingestion(
        db_session, data, audio_ref="audio/x.webm", video_ref=None, created_by="test-user"
    )
    await db_session.commit()

    assert is_new is True
    assert recording.meeting_id == meeting_id
    assert recording.duration_seconds == duration_seconds
    assert recording.interrupted == interrupted
    # capture_origin is recorded for traceability, without altering the rest of the flow
    assert recording.capture_origin == origin

    result = await db_session.execute(
        select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
    )
    persisted = result.scalar_one()
    assert persisted.audio_ref == recording.audio_ref
    assert persisted.video_ref == recording.video_ref


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(duration_seconds=st.integers(min_value=0, max_value=36_000))
@pytest.mark.asyncio
async def test_property_15_both_origins_produce_the_same_persisted_fields(
    db_session: AsyncSession, duration_seconds: int
) -> None:
    """Two equivalent ingestions that only differ in capture_origin produce the same
    persisted fields (except capture_origin itself and the keys)."""
    fields_by_origin: dict[str, SessionRecording] = {}

    for origin in ORIGINS:
        meeting_id = str(uuid.uuid4())
        data = IngestionData(
            meeting_id=meeting_id,
            idempotency_key=str(uuid.uuid4()),
            capture_origin=origin,
            duration_seconds=duration_seconds,
            interrupted=False,
            notice_issued_at=None,
        )
        recording, _ = await process_ingestion(
            db_session, data, audio_ref="audio/x.webm", video_ref=None, created_by="test-user"
        )
        await db_session.commit()
        fields_by_origin[origin] = recording

    a = fields_by_origin["chrome_extension"]
    b = fields_by_origin["server_bot"]

    assert a.duration_seconds == b.duration_seconds
    assert a.interrupted == b.interrupted
    assert a.audio_ref == b.audio_ref
    assert a.video_ref == b.video_ref
