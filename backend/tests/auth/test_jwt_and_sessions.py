"""JWT validation, mandatory signing secret, revocable sessions and per-request roles (#1069)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.router import router as auth_router
from app.auth.token import (
    JWT_ALGORITHM,
    JwtConfigurationError,
    create_token,
    decode_token,
    get_jwt_secret,
)
from app.infra.models import User
from tests.auth.helpers import add_user, get_user, login_body

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
PROBE = "/api/v1/meetings/"  # Any route behind get_current_user.
SALES_PROBE = "/api/v1/templates"  # A route behind require_sales.


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post(LOGIN, json=login_body(email))
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _forge(claims: dict[str, Any], *, secret: str | None = None, algorithm: str = "HS256") -> str:
    payload = {"exp": datetime.now(UTC) + timedelta(minutes=5), **claims}
    return jwt.encode(payload, secret or get_jwt_secret(), algorithm=algorithm)


# --- mandatory secret -----------------------------------------------------------------------------------


@pytest.fixture
def production_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    return monkeypatch


def test_missing_secret_is_an_error_outside_the_test_environment(production_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(JwtConfigurationError, match="is not set"):
        get_jwt_secret()
    with pytest.raises(JwtConfigurationError):
        create_token("u", "u@x.co", "U", True)


def test_short_secret_is_rejected_without_printing_it(production_env: pytest.MonkeyPatch) -> None:
    production_env.setenv("JWT_SECRET", "short-secret-value")
    with pytest.raises(JwtConfigurationError) as error:
        get_jwt_secret()
    assert "short-secret-value" not in str(error.value) and "shorter than 32 bytes" in str(error.value)


def test_secret_file_is_used_and_checked(production_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "jwt_secret"
    secret_file.write_text("f" * 64 + "\n", encoding="utf-8")
    production_env.setenv("JWT_SECRET_FILE", str(secret_file))
    assert get_jwt_secret() == "f" * 64
    secret_file.write_text("g" * 31, encoding="utf-8")
    with pytest.raises(JwtConfigurationError):
        get_jwt_secret()


def test_test_environment_gets_a_random_per_process_secret_not_a_fixed_one(
    production_env: pytest.MonkeyPatch,
) -> None:
    production_env.setenv("APP_ENV", "test")
    secret = get_jwt_secret()
    assert len(secret) >= 32 and secret != "dev-secret-change-in-production"
    assert decode_token(create_token("u", "u@x.co", "U", True))["sub"] == "u"


@pytest.mark.asyncio
async def test_api_refuses_to_start_without_a_valid_secret(production_env: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(auth_router)
    with pytest.raises(JwtConfigurationError):
        async with app.router.lifespan_context(app):
            pass
    production_env.setenv("JWT_SECRET", "k" * 40)
    async with app.router.lifespan_context(app):
        pass


@pytest.mark.asyncio
async def test_real_application_lifespan_includes_the_secret_check(production_env: pytest.MonkeyPatch) -> None:
    from app.main import app

    # The application lifespan runs first and now requires explicit service URLs (no built-in defaults).
    production_env.setenv("DATABASE_URL", "postgresql+asyncpg://sauri:unused@127.0.0.1:1/sauri")
    production_env.setenv("QUEUE_BROKER_URL", "amqp://sauri:unused@127.0.0.1:1/")
    with pytest.raises(JwtConfigurationError):
        async with app.router.lifespan_context(app):
            pass


def test_application_source_has_no_hardcoded_secret_fallback() -> None:
    source = (Path(__file__).parents[2] / "app" / "auth" / "token.py").read_text(encoding="utf-8")
    assert "dev-secret" not in source and "jose" not in source


# --- token validation -----------------------------------------------------------------------------------


def test_token_carries_the_expected_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    payload = decode_token(create_token("user-1", "u@x.co", "U", True, token_version=3))
    assert {"sub", "email", "name", "is_sales", "tv", "jti", "iat", "exp"} <= set(payload)
    assert payload["tv"] == 3 and payload["sub"] == "user-1"
    assert payload["exp"] - payload["iat"] == 3600
    assert create_token("a", "a@x.co", "A", True) != create_token("a", "a@x.co", "A", True)  # unique jti


@pytest.mark.asyncio
async def test_expired_tampered_and_unsigned_tokens_are_rejected(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "valid@summan.com")
    good = await _login(api_client, "valid@summan.com")
    assert (await api_client.get(PROBE, headers=_bearer(good))).status_code == 200

    expired = _forge({"sub": user_id, "exp": datetime.now(UTC) - timedelta(seconds=5)})
    head, body, signature = good.split(".")
    flipped = signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    forged_body = base64.urlsafe_b64encode(
        json.dumps({**json.loads(base64.urlsafe_b64decode(body + "==")), "sub": "someone-else"}).encode()
    ).rstrip(b"=").decode()
    unsigned = (
        base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(json.dumps({"sub": user_id, "exp": 4102444800}).encode()).rstrip(b"=").decode()
        + "."
    )
    for bad in (
        expired,
        f"{head}.{body}.{flipped}",
        f"{head}.{forged_body}.{signature}",
        unsigned,
        _forge({"sub": user_id}, secret="z" * 40),  # signed with another key
        _forge({"sub": user_id}, secret="z" * 64, algorithm="HS512"),
        "not-a-token",
    ):
        response = await api_client.get(PROBE, headers=_bearer(bad))
        assert response.status_code == 401, bad[:20]
    # Missing exp or sub are rejected as well.
    no_exp = jwt.encode({"sub": user_id}, get_jwt_secret(), algorithm=JWT_ALGORITHM)
    no_sub = _forge({})
    for bad in (no_exp, no_sub):
        assert (await api_client.get(PROBE, headers=_bearer(bad))).status_code == 401


@pytest.mark.asyncio
async def test_token_for_a_missing_account_is_rejected_outside_the_test_environment(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_user(api_session_factory, "present@summan.com")
    ghost = create_token(str(uuid.uuid4()), "ghost@summan.com", "Ghost", True)
    assert (await api_client.get(PROBE, headers=_bearer(ghost))).status_code == 200  # test environment shortcut
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "p" * 40)
    ghost = create_token(str(uuid.uuid4()), "ghost@summan.com", "Ghost", True)
    assert (await api_client.get(PROBE, headers=_bearer(ghost))).status_code == 401


# --- revocation and roles -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_revokes_every_session_of_the_user_only(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "logout@summan.com")
    await add_user(api_session_factory, "bystander@summan.com")
    first = await _login(api_client, "logout@summan.com")
    second = await _login(api_client, "logout@summan.com")
    bystander = await _login(api_client, "bystander@summan.com")
    assert decode_token(first)["tv"] == 0

    response = await api_client.post(LOGOUT, headers=_bearer(first))
    assert response.status_code == 204 and response.content == b""
    assert (await get_user(api_session_factory, user_id)).token_version == 1
    for revoked in (first, second):
        assert (await api_client.get(PROBE, headers=_bearer(revoked))).status_code == 401
        assert (await api_client.post(LOGOUT, headers=_bearer(revoked))).status_code == 401
    assert (await api_client.get(PROBE, headers=_bearer(bystander))).status_code == 200

    fresh = await _login(api_client, "logout@summan.com")
    assert decode_token(fresh)["tv"] == 1
    assert (await api_client.get(PROBE, headers=_bearer(fresh))).status_code == 200


@pytest.mark.asyncio
async def test_logout_requires_authentication(api_client: AsyncClient) -> None:
    assert (await api_client.post(LOGOUT)).status_code == 401


@pytest.mark.asyncio
async def test_tokens_issued_before_revocation_existed_keep_working_until_logout(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "old@summan.com")
    legacy = _forge({"sub": user_id, "email": "old@summan.com", "name": "Synthetic", "is_sales": True})  # no tv/jti
    assert (await api_client.get(PROBE, headers=_bearer(legacy))).status_code == 200
    assert (await api_client.post(LOGOUT, headers=_bearer(legacy))).status_code == 204
    assert (await api_client.get(PROBE, headers=_bearer(legacy))).status_code == 401


@pytest.mark.asyncio
async def test_a_token_with_a_stale_version_is_rejected(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "stale@summan.com")
    async with api_session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        user.token_version = 4
    for version, expected in ((3, 401), (5, 401), (4, 200)):
        token = create_token(user_id, "stale@summan.com", "Synthetic", True, token_version=version)
        assert (await api_client.get(PROBE, headers=_bearer(token))).status_code == expected, version


@pytest.mark.asyncio
async def test_role_is_read_from_the_database_on_every_request(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "role@summan.com", is_sales=True)
    token = await _login(api_client, "role@summan.com")
    assert decode_token(token)["is_sales"] is True
    assert (await api_client.get(SALES_PROBE, headers=_bearer(token))).status_code == 200

    async with api_session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        user.is_sales = False
    assert (await api_client.get(SALES_PROBE, headers=_bearer(token))).status_code == 403  # same token, new role

    async with api_session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        user.is_sales = True
    forged_claim = create_token(user_id, "role@summan.com", "Synthetic", False)  # a claim cannot revoke or grant
    assert (await api_client.get(SALES_PROBE, headers=_bearer(forged_claim))).status_code == 200


@pytest.mark.asyncio
async def test_a_token_claim_cannot_grant_a_role_the_account_lacks(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "norole@summan.com", is_sales=False)
    claims_sales = create_token(user_id, "norole@summan.com", "Synthetic", True)
    assert (await api_client.get(SALES_PROBE, headers=_bearer(claims_sales))).status_code == 403
