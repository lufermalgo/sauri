"""POST /api/v1/auth/login (chrome-side-panel, Tarea 13.9).

Validates: Requirements 13.2, 13.3
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from jose import jwt

from app.auth.passwords import hash_password
from app.auth.seed import seed_users
from app.auth.token import JWT_ALGORITHM, JWT_SECRET
from app.infra.models import User


@pytest.mark.asyncio
async def test_login_valid_credentials_issues_jwt(api_client: AsyncClient, api_session_factory):
    async with api_session_factory() as session, session.begin():
        session.add(
            User(
                id=str(uuid.uuid4()),
                email="valido@summan.com",
                name="Valido",
                password_hash=hash_password("clave-correcta"),
                is_sales=True,
                created_at=datetime.now(UTC),
            )
        )

    resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "valido@summan.com", "password": "clave-correcta"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    payload = jwt.decode(body["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["email"] == "valido@summan.com"
    assert payload["is_sales"] is True


@pytest.mark.asyncio
async def test_login_invalid_credentials_returns_401(api_client: AsyncClient, api_session_factory):
    async with api_session_factory() as session, session.begin():
        session.add(
            User(
                id=str(uuid.uuid4()),
                email="valido2@summan.com",
                name="Valido2",
                password_hash=hash_password("clave-correcta"),
                is_sales=True,
                created_at=datetime.now(UTC),
            )
        )

    resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "valido2@summan.com", "password": "clave-incorrecta"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(api_client: AsyncClient):
    resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "no-existe@summan.com", "password": "cualquiera"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_seed_users_is_idempotent(api_session_factory):
    async with api_session_factory() as session:
        async with session.begin():
            created1 = await seed_users(session)
        assert len(created1) == 2

    async with api_session_factory() as session:
        async with session.begin():
            created2 = await seed_users(session)
        assert len(created2) == 0
