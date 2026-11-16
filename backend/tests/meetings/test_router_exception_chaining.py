"""Tests for exception context preserved by meeting API error translation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.schemas import AuthenticatedUser
from app.infra.models import Meeting
from app.meetings import router
from app.meetings.schemas import MeetingCreate


@pytest.fixture
def authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id="test-user",
        email="test@sauri.local",
        name="Test User",
        is_sales=True,
    )


@pytest.mark.asyncio
async def test_create_meeting_chains_value_error_as_http_422_cause(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_user: AuthenticatedUser,
    async_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(router, "create_engine", lambda: async_engine)
    monkeypatch.setattr(router, "create_session_factory", lambda _: session_factory)

    async def _reject(*_args: object, **_kwargs: object) -> None:
        raise ValueError("Invalid input: internal detail that must not reach the client")

    monkeypatch.setattr(router, "register_meeting", _reject)

    with pytest.raises(HTTPException) as raised:
        await router.create_meeting(
            MeetingCreate(meet_link="https://meet.google.com/abc-defg-hij"), authenticated_user
        )

    assert raised.value.status_code == 422
    assert raised.value.detail == "invalid_request"
    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__).startswith("Invalid input:")


@pytest.mark.asyncio
async def test_get_meeting_missing_meeting_returns_helper_404(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_user: AuthenticatedUser,
    async_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(router, "create_engine", lambda: async_engine)
    monkeypatch.setattr(router, "create_session_factory", lambda _: session_factory)

    with pytest.raises(HTTPException) as raised:
        await router.get_meeting_endpoint("missing-meeting", authenticated_user)

    assert raised.value.status_code == 404
    assert raised.value.detail == "not_found"


@pytest.mark.asyncio
async def test_get_meeting_chains_value_error_as_http_404_cause(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_user: AuthenticatedUser,
    async_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(router, "create_engine", lambda: async_engine)
    monkeypatch.setattr(router, "create_session_factory", lambda _: session_factory)

    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id="missing-meeting",
            meet_link="https://meet.google.com/abc-defg-hij",
            title="Synthetic",
            origin="link",
            calendar_invite_id=None,
            scheduled_start_time=None,
            process_state="queued",
            failure_cause=None,
            created_by=authenticated_user.id,
            created_at=datetime.now(UTC),
        ))

    async def _raise(_session: AsyncSession, _meeting_id: str) -> None:
        raise ValueError("Meeting not found: missing-meeting")

    monkeypatch.setattr(router, "get_meeting", _raise)
    with pytest.raises(HTTPException) as raised:
        await router.get_meeting_endpoint("missing-meeting", authenticated_user)

    assert raised.value.status_code == 404
    assert raised.value.detail == "not_found"
    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__) == "Meeting not found: missing-meeting"
