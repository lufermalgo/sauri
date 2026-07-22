"""AUTH_DISABLED restricted to the test environment (chrome-side-panel, Tarea 13.11).

Validates: Requirements 13.1, 13.4
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.dependencies import get_current_user


@pytest.mark.asyncio
async def test_bypass_active_in_test_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("APP_ENV", "test")

    user = await get_current_user(credentials=None)
    assert user.id == "dev-user-00000000"


@pytest.mark.asyncio
async def test_bypass_inactive_outside_test_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(HTTPException):
        await get_current_user(credentials=None)


@pytest.mark.asyncio
async def test_bypass_inactive_without_app_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(HTTPException):
        await get_current_user(credentials=None)
