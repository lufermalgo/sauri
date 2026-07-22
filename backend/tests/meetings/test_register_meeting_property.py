"""Property tests for register_meeting (service.py).

# Feature: meeting-capture-transcription, Property 1: Registering a Meeting starts in "queued"
# Feature: meeting-capture-transcription, Property 2: Acceptance of Meeting input types
Tasks: 5.5, 5.6
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.meetings.service import register_meeting

meet_link_strategy = st.from_regex(r"[a-z]{3,4}-[a-z]{4}-[a-z]{3}", fullmatch=True).map(
    lambda code: f"https://meet.google.com/{code}"
)

invalid_link_strategy = st.one_of(
    st.just("http://meet.google.com/abc-defg-hij"),
    st.just("https://zoom.us/j/123456"),
    st.just(""),
    st.text(max_size=10).filter(lambda s: not s.startswith("https://meet.google.com/")),
)


# ---------------------------------------------------------------------------
# Property 1: Registering a Meeting starts in "queued"
# Feature: meeting-capture-transcription, Property 1: Registering a Meeting starts in "queued"
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(link=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_1_registration_starts_queued(
    db_session: AsyncSession, link: str
) -> None:
    """Every validly registered Meeting starts in state 'queued'."""
    meeting = await register_meeting(
        db_session, {"meet_link": link}, created_by="test-user"
    )

    assert meeting.process_state == "queued"
    assert meeting.failure_cause is None


# ---------------------------------------------------------------------------
# Property 2: Acceptance of Meeting input types
# Feature: meeting-capture-transcription, Property 2: Acceptance of Meeting input types
# Validates: Requirements 1.7
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(link=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_2_accepts_link_input(
    db_session: AsyncSession, link: str
) -> None:
    """Direct-link input is accepted and produces origin='link'."""
    meeting = await register_meeting(
        db_session, {"meet_link": link}, created_by="test-user"
    )
    assert meeting.origin == "link"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(link=meet_link_strategy, invite_id=st.text(min_size=1, max_size=30))
@pytest.mark.asyncio
async def test_property_2_accepts_calendar_input(
    db_session: AsyncSession, link: str, invite_id: str
) -> None:
    """Calendar-invite input is accepted and produces origin='calendar_invite'."""
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting = await register_meeting(
        db_session,
        {
            "meet_link": link,
            "calendar_invite_id": invite_id,
            "scheduled_start_time": start_time,
        },
        created_by="test-user",
    )
    assert meeting.origin == "calendar_invite"
    assert meeting.calendar_invite_id == invite_id


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(link=meet_link_strategy)
@pytest.mark.asyncio
async def test_property_2_accepts_manual_input(
    db_session: AsyncSession, link: str
) -> None:
    """Manual request (type='manual') is accepted and produces origin='manual'."""
    meeting = await register_meeting(
        db_session, {"meet_link": link, "type": "manual"}, created_by="test-user"
    )
    assert meeting.origin == "manual"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(invalid_link=invalid_link_strategy)
@pytest.mark.asyncio
async def test_property_2_rejects_invalid_links(
    db_session: AsyncSession, invalid_link: str
) -> None:
    """Any input with an invalid Google Meet link is rejected."""
    with pytest.raises(ValueError):
        await register_meeting(
            db_session, {"meet_link": invalid_link}, created_by="test-user"
        )
