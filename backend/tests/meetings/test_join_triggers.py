"""Unit tests for the join triggers (request_join, schedule_join_by_calendar).

# Feature: meeting-capture-transcription
Task: 5.10 — Validates: Requirements 1.2, 1.3
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting
from app.meetings.service import request_join, schedule_join_by_calendar


def _create_queued_meeting(meeting_id: str) -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="queued",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_request_join_manual_transitions_and_enqueues(db_session: AsyncSession) -> None:
    """Req 1.2: manual join transitions to 'joining' and enqueues a join job."""
    meeting_id = str(uuid.uuid4())
    meeting = _create_queued_meeting(meeting_id)
    db_session.add(meeting)
    await db_session.flush()

    queue = AsyncMock()
    result = await request_join(db_session, meeting_id, queue)

    assert result.successful is True
    assert result.new_state == "joining"
    queue.publicar.assert_awaited_once_with(
        tema="join",
        mensaje={"meeting_id": meeting_id, "meet_link": meeting.meet_link},
    )


@pytest.mark.asyncio
async def test_request_join_nonexistent_meeting_does_not_publish(
    db_session: AsyncSession,
) -> None:
    """If the Meeting doesn't exist, no job is published."""
    queue = AsyncMock()
    result = await request_join(db_session, "does-not-exist", queue)

    assert result.successful is False
    queue.publicar.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_join_by_calendar_fires_when_the_time_arrives(
    db_session: AsyncSession,
) -> None:
    """Req 1.3: the calendar-scheduled trigger transitions and enqueues just like a manual join."""
    meeting_id = str(uuid.uuid4())
    meeting = _create_queued_meeting(meeting_id)
    meeting.origin = "calendar_invite"
    meeting.calendar_invite_id = "cal-evt-1"
    meeting.scheduled_start_time = datetime.now(UTC)
    db_session.add(meeting)
    await db_session.flush()

    queue = AsyncMock()
    result = await schedule_join_by_calendar(db_session, meeting_id, queue)

    assert result.successful is True
    assert result.new_state == "joining"
    queue.publicar.assert_awaited_once_with(
        tema="join",
        mensaje={"meeting_id": meeting_id, "meet_link": meeting.meet_link},
    )
