"""Contract tests for meetings created by web uploads without Meet links."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.infra.models import Meeting
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion


@pytest.mark.asyncio
async def test_upload_created_meeting_keeps_missing_meet_link_null(
    db_session: AsyncSession,
) -> None:
    meeting_id = str(uuid.uuid4())
    data = IngestionData(
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        video_presence="muxed",
        duration_seconds=12,
        meet_link=None,
    )

    await process_ingestion(
        db_session,
        data,
        audio_ref="synthetic/audio.webm",
        video_ref=None,
        created_by="synthetic-user",
    )

    meeting = await db_session.get(Meeting, meeting_id)
    assert meeting is not None
    assert meeting.meet_link is None


@pytest.mark.asyncio
async def test_meetings_schema_allows_a_null_meet_link(async_engine: AsyncEngine) -> None:
    def meet_link_is_nullable(connection: Connection) -> bool:
        columns = sa_inspect(connection).get_columns("meetings")
        meet_link = next(column for column in columns if column["name"] == "meet_link")
        return bool(meet_link["nullable"])

    async with async_engine.connect() as connection:
        nullable = await connection.run_sync(meet_link_is_nullable)

    assert nullable
