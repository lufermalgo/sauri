"""Access control and audit property test (authorization.py, audit.py).

# Feature: meeting-capture-transcription, Property 10: Access control and audit
Task: 8.2 — Validates: Requirements 7.3, 7.4, 9.1, 9.2, 9.3
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.authorization import require_sales, verify_authorization
from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.infra.models import AccessLog


def _build_app(session_factory: async_sessionmaker[AsyncSession], user: AuthenticatedUser) -> FastAPI:
    app = FastAPI()

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    dependency = Depends(require_sales(get_session))

    @app.get("/protected-resource")
    async def endpoint(
        authorized_user: AuthenticatedUser = dependency,
    ) -> dict[str, str]:
        return {"id": authorized_user.id}

    app.dependency_overrides[get_current_user] = lambda: user
    return app


# ---------------------------------------------------------------------------
# Property 10: Access control and audit
# Feature: meeting-capture-transcription, Property 10: Access control and audit
# Validates: Requirements 7.3, 7.4, 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(is_sales=st.booleans())
@pytest.mark.asyncio
async def test_property_10_access_granted_iff_authorized(
    session_factory: async_sessionmaker[AsyncSession], is_sales: bool
) -> None:
    """Access is granted if and only if the authenticated user is sales (authorized)."""
    user = AuthenticatedUser(
        id="user-1", email="u@sauri.local", name="U", is_sales=is_sales
    )
    assert verify_authorization(user, "resource", "GET") is is_sales

    app = _build_app(session_factory, user)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/protected-resource")

    if is_sales:
        assert response.status_code == 200
    else:
        assert response.status_code == 403


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(is_sales=st.booleans())
@pytest.mark.asyncio
async def test_property_10_every_denial_generates_exactly_one_record(
    session_factory: async_sessionmaker[AsyncSession], is_sales: bool
) -> None:
    """Every access denial generates exactly one AccessLog entry with result='denied'."""
    user = AuthenticatedUser(
        id=str(uuid.uuid4()), email="u2@sauri.local", name="U2", is_sales=is_sales
    )
    app = _build_app(session_factory, user)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/protected-resource")

    async with session_factory() as session:
        result = await session.execute(
            select(AccessLog).where(AccessLog.user_id == user.id)
        )
        records = result.scalars().all()

    if is_sales:
        assert records == []
    else:
        assert len(records) == 1
        assert records[0].result == "denied"
