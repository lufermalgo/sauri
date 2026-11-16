"""Rotating refresh tokens for the Chrome extension session (#1123)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import rate_limit
from app.auth import refresh as refresh_service
from app.auth.seed_admin import ensure_admin
from app.auth.token import decode_token
from app.infra.models import AccessLog, AuthRefreshToken, LoginAttempt
from tests.auth.helpers import PASSWORD, add_user, get_user, login_body

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
REFRESH = "/api/v1/auth/refresh"
REVOKE = "/api/v1/auth/refresh/revoke"
PROBE = "/api/v1/meetings/"  # Any route behind get_current_user.
UNIFORM_401 = {"detail": "Invalid or expired refresh token"}


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture(autouse=True)
def auth_logger_enabled() -> None:
    # An earlier in-process `alembic upgrade` (logging.fileConfig) disables already-created loggers.
    logging.getLogger("sauri.auth").disabled = False


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    fake = FakeClock()
    monkeypatch.setattr(refresh_service, "utcnow", fake)
    monkeypatch.setattr(rate_limit, "utcnow", fake)
    yield fake


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _extension_login(client: AsyncClient, email: str) -> dict[str, object]:
    response = await client.post(LOGIN, json={**login_body(email), "client": "extension"})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def _refresh(client: AsyncClient, token: str) -> tuple[int, dict[str, object]]:
    response = await client.post(REFRESH, json={"refresh_token": token})
    return response.status_code, response.json()


async def _rows(factory: async_sessionmaker[AsyncSession]) -> list[AuthRefreshToken]:
    async with factory() as session:
        return list((await session.execute(select(AuthRefreshToken).order_by(AuthRefreshToken.issued_at))).scalars())


# --- issuing --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_login_response_carries_no_refresh_token_and_stores_none(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "portal@summan.com")
    response = await api_client.post(LOGIN, json=login_body("portal@summan.com"))
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.json()["expires_in"] == 3600  # The access token lifetime is unchanged.
    assert await _rows(api_session_factory) == []


@pytest.mark.asyncio
async def test_extension_login_returns_a_refresh_token_and_stores_only_its_digest(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    user_id = await add_user(api_session_factory, "ext@summan.com")
    body = await _extension_login(api_client, "ext@summan.com")
    assert body["expires_in"] == 3600
    token = str(body["refresh_token"])
    assert len(token) >= 43  # 256 bits, URL-safe base64.
    assert body["refresh_expires_in"] == 30 * 24 * 3600

    [row] = await _rows(api_session_factory)
    assert row.user_id == user_id
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {str(getattr(row, column.name)) for column in AuthRefreshToken.__table__.columns}
    assert row.rotated_at is None and row.revoked_at is None and row.last_used_at is None
    assert row.absolute_expires_at - row.issued_at == timedelta(days=90)
    assert row.idle_expires_at - row.issued_at == timedelta(days=30)


@pytest.mark.asyncio
async def test_unknown_client_value_is_rejected(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "bad@summan.com")
    response = await api_client.post(LOGIN, json={**login_body("bad@summan.com"), "client": "portal"})
    assert response.status_code == 422


# --- rotation -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_rotates_the_token_and_returns_a_working_access_token(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    user_id = await add_user(api_session_factory, "rotate@summan.com")
    first = str((await _extension_login(api_client, "rotate@summan.com"))["refresh_token"])
    clock.advance(minutes=61)  # The access token from login would have expired by now.

    status, body = await _refresh(api_client, first)
    assert status == 200
    assert body["expires_in"] == 3600 and body["token_type"] == "bearer"
    second = str(body["refresh_token"])
    assert second != first
    assert decode_token(str(body["access_token"]))["sub"] == user_id
    assert (await api_client.get(PROBE, headers=_bearer(str(body["access_token"])))).status_code == 200

    old, new = await _rows(api_session_factory)
    assert old.rotated_at is not None and old.last_used_at is not None and old.revoked_at is None
    assert new.family_id == old.family_id and new.rotated_at is None
    assert new.absolute_expires_at == old.absolute_expires_at  # The family never extends its 90 days.

    # The successor works, and the retired token no longer does.
    assert (await _refresh(api_client, second))[0] == 200


@pytest.mark.asyncio
async def test_idle_expiry_slides_but_never_passes_the_absolute_limit(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "slide@summan.com")
    token = str((await _extension_login(api_client, "slide@summan.com"))["refresh_token"])
    body: dict[str, object] = {}
    for _ in range(3):  # Days 25, 50 and 75: each use is within the 30 idle days of the previous token.
        clock.advance(days=25)
        status, body = await _refresh(api_client, token)
        assert status == 200
        token = str(body["refresh_token"])
    # The day-75 token would be idle-valid for 30 days, but only 15 days of the 90-day family remain.
    assert body["refresh_expires_in"] == 15 * 24 * 3600
    clock.advance(days=16)
    assert (await _refresh(api_client, token))[0] == 401


@pytest.mark.asyncio
async def test_idle_expiry_rejects_with_the_uniform_error(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "idle@summan.com")
    token = str((await _extension_login(api_client, "idle@summan.com"))["refresh_token"])
    clock.advance(days=30, seconds=1)
    response = await api_client.post(REFRESH, json={"refresh_token": token})
    assert response.status_code == 401 and response.json() == UNIFORM_401


@pytest.mark.asyncio
async def test_absolute_expiry_rejects_even_for_a_recently_used_family(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "absolute@summan.com")
    token = str((await _extension_login(api_client, "absolute@summan.com"))["refresh_token"])
    for _ in range(3):
        clock.advance(days=29)
        status, body = await _refresh(api_client, token)
        assert status == 200
        token = str(body["refresh_token"])
    clock.advance(days=4)  # Day 91: used 4 days ago, but the family is past 90 days.
    assert (await _refresh(api_client, token))[0] == 401


# --- reuse and revocation -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reusing_a_rotated_token_revokes_the_whole_family(
    api_client: AsyncClient,
    api_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_user(api_session_factory, "reuse@summan.com")
    first = str((await _extension_login(api_client, "reuse@summan.com"))["refresh_token"])
    status, body = await _refresh(api_client, first)
    assert status == 200
    second = str(body["refresh_token"])
    other_family = str((await _extension_login(api_client, "reuse@summan.com"))["refresh_token"])

    with caplog.at_level(logging.DEBUG):
        replay = await api_client.post(REFRESH, json={"refresh_token": first})
    assert replay.status_code == 401 and replay.json() == UNIFORM_401
    assert "family revoked" in caplog.text

    # The newest token of the family died with it; another family of the same user is untouched.
    assert (await _refresh(api_client, second))[0] == 401
    assert (await _refresh(api_client, other_family))[0] == 200
    rows = await _rows(api_session_factory)  # The replayed family is revoked; the other one is untouched.
    assert [row.revoked_at is not None for row in rows] == [True, True, False, False]


@pytest.mark.asyncio
async def test_unknown_malformed_and_revoked_tokens_get_the_identical_response(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "uniform@summan.com")
    live = str((await _extension_login(api_client, "uniform@summan.com"))["refresh_token"])
    revoked = str((await _extension_login(api_client, "uniform@summan.com"))["refresh_token"])
    assert (await api_client.post(REVOKE, json={"refresh_token": revoked})).status_code == 204

    responses = [
        await api_client.post(REFRESH, json={"refresh_token": token})
        for token in ("not-a-token", "A" * 43, revoked, "x" * 512)
    ]
    assert [(r.status_code, r.json()) for r in responses] == [(401, UNIFORM_401)] * 4
    assert all(r.headers["WWW-Authenticate"] == "Bearer" for r in responses)
    assert (await _refresh(api_client, live))[0] == 200  # An unrelated family still works.


@pytest.mark.asyncio
async def test_bad_request_shapes_are_422_without_echoing_input(api_client: AsyncClient) -> None:
    for payload in ({}, {"refresh_token": ""}, {"refresh_token": "t" * 513}, {"refresh_token": "t", "extra": 1}):
        response = await api_client.post(REFRESH, json=payload)
        assert response.status_code == 422
        assert "t" * 20 not in response.text


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_family_and_the_access_token(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "bye@summan.com")
    body = await _extension_login(api_client, "bye@summan.com")
    refresh_token, access = str(body["refresh_token"]), str(body["access_token"])
    assert (await api_client.post(LOGOUT, headers=_bearer(access))).status_code == 204
    assert (await _refresh(api_client, refresh_token))[0] == 401
    assert all(row.revoked_at is not None for row in await _rows(api_session_factory))


@pytest.mark.asyncio
async def test_portal_logout_also_revokes_the_extension_refresh_tokens(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "both@summan.com")
    extension = str((await _extension_login(api_client, "both@summan.com"))["refresh_token"])
    portal = (await api_client.post(LOGIN, json=login_body("both@summan.com"))).json()["access_token"]
    assert (await api_client.post(LOGOUT, headers=_bearer(portal))).status_code == 204
    assert (await _refresh(api_client, extension))[0] == 401


@pytest.mark.asyncio
async def test_revoke_endpoint_ends_the_session_without_an_access_token_and_is_uniform(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "rev@summan.com")
    token = str((await _extension_login(api_client, "rev@summan.com"))["refresh_token"])
    known = await api_client.post(REVOKE, json={"refresh_token": token})
    unknown = await api_client.post(REVOKE, json={"refresh_token": "never-issued"})
    assert (known.status_code, known.content) == (unknown.status_code, unknown.content) == (204, b"")
    assert (await _refresh(api_client, token))[0] == 401


@pytest.mark.asyncio
async def test_revoking_a_rotated_token_still_ends_the_family(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_user(api_session_factory, "late@summan.com")
    first = str((await _extension_login(api_client, "late@summan.com"))["refresh_token"])
    status, body = await _refresh(api_client, first)
    assert status == 200
    assert (await api_client.post(REVOKE, json={"refresh_token": first})).status_code == 204
    assert (await _refresh(api_client, str(body["refresh_token"])))[0] == 401


@pytest.mark.asyncio
async def test_password_reset_revokes_every_refresh_token(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with api_session_factory() as session, session.begin():
        admin, _ = await ensure_admin(session, "synthetic-admin-password-1", reset_password=False)
        email, admin_id = admin.email, admin.id
    login = await api_client.post(
        LOGIN, json={"email": email, "password": "synthetic-admin-password-1", "client": "extension"}
    )
    assert login.status_code == 200
    token = login.json()["refresh_token"]

    async with api_session_factory() as session, session.begin():
        await ensure_admin(session, "synthetic-admin-password-2", reset_password=True)
    assert (await get_user(api_session_factory, admin_id)).token_version == 1
    assert all(row.revoked_at is not None for row in await _rows(api_session_factory))
    assert (await _refresh(api_client, token))[0] == 401


@pytest.mark.asyncio
async def test_a_token_version_change_alone_rejects_and_revokes_the_family(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "tv@summan.com")
    token = str((await _extension_login(api_client, "tv@summan.com"))["refresh_token"])
    async with api_session_factory() as session, session.begin():
        user = await get_user(api_session_factory, user_id)
        user = await session.merge(user)
        user.token_version += 1  # Any other path that bumps the version, not going through the revoke call.
    response = await api_client.post(REFRESH, json={"refresh_token": token})
    assert response.status_code == 401 and response.json() == UNIFORM_401
    [row] = await _rows(api_session_factory)
    assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_a_deleted_account_cannot_refresh(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await add_user(api_session_factory, "gone@summan.com")
    token = str((await _extension_login(api_client, "gone@summan.com"))["refresh_token"])
    async with api_session_factory() as session, session.begin():
        user = await session.get(type(await get_user(api_session_factory, user_id)), user_id)
        assert user is not None
        await session.delete(user)
    response = await api_client.post(REFRESH, json={"refresh_token": token})
    assert response.status_code == 401 and response.json() == UNIFORM_401


# --- rate limit -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_refreshes_lock_the_address_with_a_uniform_429(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "limit@summan.com")
    valid = str((await _extension_login(api_client, "limit@summan.com"))["refresh_token"])
    threshold = rate_limit.REFRESH_THRESHOLD
    statuses = [(await _refresh(api_client, f"guess-{i}"))[0] for i in range(threshold)]
    assert statuses == [401] * threshold

    locked = await api_client.post(REFRESH, json={"refresh_token": "guess-more"})
    assert locked.status_code == 429
    assert locked.json() == {"detail": "Too many refresh attempts"}
    assert locked.headers["Retry-After"] == str(rate_limit.BASE_LOCKOUT_SECONDS + 1)
    # A valid token is refused while locked, so a guess cannot be confirmed.
    assert (await _refresh(api_client, valid))[0] == 429

    clock.advance(seconds=rate_limit.BASE_LOCKOUT_SECONDS + 2)
    assert (await _refresh(api_client, valid))[0] == 200


@pytest.mark.asyncio
async def test_failures_are_audited_and_counted_without_storing_tokens_or_addresses_in_the_clear(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    secret_guess = "guess-that-must-not-be-stored"
    assert (await _refresh(api_client, secret_guess))[0] == 401
    async with api_session_factory() as session:
        counters = list(
            (await session.execute(select(LoginAttempt).where(LoginAttempt.scope == "refresh_ip"))).scalars()
        )
        logged = list((await session.execute(select(AccessLog))).scalars())
    assert [counter.failures for counter in counters] == [1]
    assert [entry.result for entry in logged] == ["denied"]
    stored = " ".join([counters[0].key_hash, logged[0].resource])
    assert secret_guess not in stored
    assert hashlib.sha256(secret_guess.encode()).hexdigest() not in stored


@pytest.mark.asyncio
async def test_refresh_never_logs_a_token(
    api_client: AsyncClient,
    api_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_user(api_session_factory, "quiet@summan.com")
    first = str((await _extension_login(api_client, "quiet@summan.com"))["refresh_token"])
    status, body = await _refresh(api_client, first)
    with caplog.at_level(logging.DEBUG):
        await api_client.post(REFRESH, json={"refresh_token": first})  # Reuse: logs a warning.
        await api_client.post(REFRESH, json={"refresh_token": "other-bad-guess"})
        await api_client.post(REVOKE, json={"refresh_token": str(body["refresh_token"])})
    # Driver statement logs (SQLAlchemy, aiosqlite) are off in production and are not the application's.
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("sauri"))
    assert "refresh rejected" in logged
    forbidden = [first, str(body["refresh_token"]), str(body["access_token"]), "other-bad-guess"]
    forbidden += [hashlib.sha256(value.encode()).hexdigest() for value in forbidden]
    assert status == 200 and not [value for value in forbidden if value in logged], logged


# --- housekeeping ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spent_rows_are_pruned_after_the_retention_window(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "prune@summan.com")
    token = str((await _extension_login(api_client, "prune@summan.com"))["refresh_token"])
    for _ in range(3):
        clock.advance(days=1)
        token = str((await _refresh(api_client, token))[1]["refresh_token"])
    assert len(await _rows(api_session_factory)) == 4  # A recently rotated token stays to catch replays.
    clock.advance(days=refresh_service.RETENTION_DAYS + 1)
    assert (await _refresh(api_client, token))[0] == 200
    async with api_session_factory() as session:
        remaining = (await session.execute(select(func.count()).select_from(AuthRefreshToken))).scalar_one()
    assert remaining == 2  # Rows rotated more than a week ago are gone; the previous and the new one remain.


@pytest.mark.asyncio
async def test_password_is_not_needed_again_for_a_refresh(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The refresh request carries the token only: no email, no password."""
    await add_user(api_session_factory, "nopw@summan.com", password=PASSWORD)
    token = str((await _extension_login(api_client, "nopw@summan.com"))["refresh_token"])
    assert (await api_client.post(REFRESH, json={"refresh_token": token, "password": PASSWORD})).status_code == 422
