"""Timing equalization, input bounds and transparent rehash on login (#1069)."""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import router as auth_router
from app.auth.passwords import hash_password, verify_password
from app.auth.schemas import MAX_EMAIL_LENGTH, MAX_PASSWORD_LENGTH
from tests.auth.helpers import PASSWORD, add_user, get_user, legacy_hash, login_body

LOGIN = "/api/v1/auth/login"
RUNS = 9


@pytest.mark.asyncio
async def test_unknown_and_wrong_password_do_the_same_hashing_work(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_user(api_session_factory, "work@summan.com")
    real_verify, real_dummy = auth_router.verify_password, auth_router.verify_dummy_password
    calls: list[str] = []

    def spy_verify(password: str, password_hash: str) -> bool:
        calls.append("real")
        return real_verify(password, password_hash)

    def spy_dummy(password: str) -> None:
        calls.append("dummy")
        real_dummy(password)

    monkeypatch.setattr(auth_router, "verify_password", spy_verify)
    monkeypatch.setattr(auth_router, "verify_dummy_password", spy_dummy)
    assert (await api_client.post(LOGIN, json=login_body("work@summan.com", "wrong"))).status_code == 401
    assert (await api_client.post(LOGIN, json=login_body("missing@summan.com", "wrong"))).status_code == 401
    assert calls == ["real", "dummy"]  # exactly one full-cost hash verification each


@pytest.mark.asyncio
async def test_response_time_does_not_reveal_whether_the_account_exists(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    shared_hash = hash_password(PASSWORD)
    for index in range(RUNS):
        await add_user(api_session_factory, f"known{index}@summan.com", password_hash=shared_hash)
    # Warm up lazy state (dummy hash, connection setup) so it is not counted.
    await api_client.post(LOGIN, json=login_body("warm@summan.com", "wrong"))

    async def timed(email: str) -> float:
        start = time.perf_counter()
        response = await api_client.post(LOGIN, json=login_body(email, "wrong-password"))
        assert response.status_code == 401
        return time.perf_counter() - start

    known: list[float] = []
    unknown: list[float] = []
    for index in range(RUNS):  # Interleaved, one fresh email each so the rate limiter never interferes.
        known.append(await timed(f"known{index}@summan.com"))
        unknown.append(await timed(f"unknown{index}@summan.com"))
    ratio = statistics.median(known) / statistics.median(unknown)
    assert 1 / 1.5 < ratio < 1.5, (statistics.median(known), statistics.median(unknown))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": "secret-value-1"},
        {"email": "a@b", "password": "secret-value-2"},
        {"email": "a b@summan.com", "password": "secret-value-3"},
        {"email": "x" * 250 + "@summan.com", "password": "secret-value-4"},
        {"email": "ok@summan.com", "password": ""},
        {"email": "ok@summan.com", "password": "p" * (MAX_PASSWORD_LENGTH + 1)},
        {"email": "ok@summan.com", "password": "secret-value-5", "role": "admin"},
        {"email": 12, "password": "secret-value-6"},
        {"password": "secret-value-7"},
    ],
)
async def test_invalid_login_bodies_get_422_that_does_not_echo_the_password(
    api_client: AsyncClient, body: dict[str, Any]
) -> None:
    response = await api_client.post(LOGIN, json=body)
    assert response.status_code == 422
    assert "secret-value" not in response.text
    assert "p" * 20 not in response.text
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


@pytest.mark.asyncio
async def test_malformed_json_does_not_echo_the_body(api_client: AsyncClient) -> None:
    response = await api_client.post(
        LOGIN,
        content=b'{"email": "a@b.co", "password": "secret-value-9"',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert "secret-value" not in response.text


@pytest.mark.asyncio
async def test_boundary_sized_values_are_accepted(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    local = "a" * 64
    domain = ".".join(["b" * 60] * 3) + ".com"
    email = f"{local}@{domain}"
    assert len(email) <= MAX_EMAIL_LENGTH
    long_password = "p" * MAX_PASSWORD_LENGTH
    await add_user(api_session_factory, email, password=long_password)
    response = await api_client.post(LOGIN, json=login_body(email, long_password))
    assert response.status_code == 200
    seeded = await api_client.post(LOGIN, json=login_body("admin@sauri.local", "irrelevant"))
    assert seeded.status_code == 401  # a `.local` seeded address is syntactically accepted


@pytest.mark.asyncio
async def test_legacy_hash_is_upgraded_to_argon2id_on_successful_login(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "legacy@summan.com", password_hash=legacy_hash(PASSWORD))
    wrong = await api_client.post(LOGIN, json=login_body("legacy@summan.com", "wrong"))
    assert wrong.status_code == 401
    assert (await get_user(api_session_factory, user_id)).password_hash.startswith("pbkdf2_sha256$")

    assert (await api_client.post(LOGIN, json=login_body("legacy@summan.com"))).status_code == 200
    upgraded = (await get_user(api_session_factory, user_id)).password_hash
    assert upgraded.startswith("$argon2id$") and verify_password(PASSWORD, upgraded)

    assert (await api_client.post(LOGIN, json=login_body("legacy@summan.com"))).status_code == 200
    assert (await get_user(api_session_factory, user_id)).password_hash == upgraded  # not rehashed again
