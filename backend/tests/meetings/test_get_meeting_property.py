"""Property test for state lookup consistency (get_meeting).

# Feature: meeting-capture-transcription, Property 5: State lookup consistency
Task: 5.8
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting
from app.meetings.service import get_meeting
from app.meetings.state_machine import STATES, VALID_FAILURE_CAUSES


def _create_meeting(state: str, failure_cause: str | None) -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state=state,
        failure_cause=failure_cause,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 5: State lookup consistency
# Feature: meeting-capture-transcription, Property 5: State lookup consistency
# Validates: Requirements 4.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    state=st.sampled_from(sorted(STATES)),
    failure_cause=st.sampled_from(sorted(VALID_FAILURE_CAUSES)),
)
@pytest.mark.asyncio
async def test_property_5_failure_cause_present_iff_failed(
    db_session: AsyncSession, state: str, failure_cause: str
) -> None:
    """failure_cause appears in the result if and only if process_state == 'failed'."""
    meeting = _create_meeting(state, failure_cause if state == "failed" else None)
    db_session.add(meeting)
    await db_session.flush()

    result = await get_meeting(db_session, meeting.id)

    assert result["process_state"] == state
    assert result["meeting_id"] == meeting.id

    if state == "failed":
        assert "failure_cause" in result
        assert result["failure_cause"] == failure_cause
    else:
        assert "failure_cause" not in result


@pytest.mark.asyncio
async def test_example_get_nonexistent_meeting_raises_error(
    db_session: AsyncSession,
) -> None:
    """Looking up a nonexistent Meeting raises ValueError."""
    with pytest.raises(ValueError):
        await get_meeting(db_session, "does-not-exist")
