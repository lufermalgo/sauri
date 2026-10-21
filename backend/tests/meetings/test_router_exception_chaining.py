"""Tests for exception context preserved by meeting API error translation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.schemas import AuthenticatedUser
from app.meetings import router


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

    with pytest.raises(HTTPException) as raised:
        await router.create_meeting({}, authenticated_user)

    assert raised.value.status_code == 422
    assert str(raised.value.detail).startswith("Invalid input:")
    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__).startswith("Invalid input:")


@pytest.mark.asyncio
async def test_get_meeting_chains_value_error_as_http_404_cause(
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
    assert raised.value.detail == "Meeting not found: missing-meeting"
    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__) == "Meeting not found: missing-meeting"
