"""Property test for state lookup consistency (get_meeting).

# Feature: meeting-capture-transcription, Property 5: State lookup consistency
Task: 5.8
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.token import create_token
from app.infra.models import Meeting, SessionRecording
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


# chrome-recording-completion T1.4 / R3.1–R3.4, R5.3: the status read
# itself is an authorization boundary; a correct service lookup is insufficient.
def _status_headers(user_id: str) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Synthetic User", True)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "joining", "recording", "transcribing", "completed", "failed"])
async def test_status_route_restricts_an_existing_meeting_to_its_owner(
    api_client: AsyncClient, api_db_url: str, state: str,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    meeting = _create_meeting(state, "synthetic failure" if state == "failed" else None)
    meeting.created_by = "status-owner"
    recording_id = str(uuid.uuid4())
    engine = create_async_engine(api_db_url)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session, session.begin():
            session.add(meeting)
            await session.flush()
            session.add(SessionRecording(
                id=recording_id, meeting_id=meeting.id, idempotency_key=recording_id,
                capture_origin="chrome_extension", audio_ref="synthetic-audio",
                duration_seconds=1, interrupted=False, finished_at=datetime.now(UTC),
                video_presence="muxed",
            ))
    finally:
        await engine.dispose()

    path = f"/api/v1/meetings/{meeting.id}"
    owner = await api_client.get(path, headers=_status_headers("status-owner"))
    assert owner.status_code == 200
    assert owner.json()["meeting_id"] == meeting.id
    assert owner.json()["process_state"] == state
    assert owner.json()["recording_id"] == recording_id

    anonymous = await api_client.get(path)
    assert anonymous.status_code == 401
    assert "process_state" not in anonymous.text
    assert "recording_id" not in anonymous.text
    assert recording_id not in anonymous.text

    stranger = await api_client.get(path, headers=_status_headers("status-stranger"))
    missing = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}", headers=_status_headers("status-stranger"))
    assert stranger.status_code == missing.status_code == 404
    assert stranger.json() == missing.json() == {"detail": "Meeting not found"}
    assert all(
        secret not in stranger.text
        for secret in (meeting.id, recording_id, state, "process_state", "recording_id")
    )
