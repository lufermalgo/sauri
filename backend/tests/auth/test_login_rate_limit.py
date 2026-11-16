"""Login rate limiting: lockout, backoff, isolation, reset and uniform 429 (#1069)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import rate_limit
from app.infra.models import AccessLog, LoginAttempt
from tests.auth.helpers import add_user, login_body

LOGIN = "/api/v1/auth/login"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    fake = FakeClock()
    monkeypatch.setattr(rate_limit, "utcnow", fake)
    yield fake


async def _fail(client: AsyncClient, email: str, times: int = 1) -> list[int]:
    return [(await client.post(LOGIN, json=login_body(email, "wrong-password"))).status_code for _ in range(times)]


@pytest.mark.asyncio
async def test_fifth_failure_is_401_and_the_sixth_attempt_is_locked(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "lock@summan.com")
    assert await _fail(api_client, "lock@summan.com", 5) == [401] * 5
    locked = await api_client.post(LOGIN, json=login_body("lock@summan.com", "wrong-password"))
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == str(rate_limit.BASE_LOCKOUT_SECONDS + 1)
    # Even the correct password is refused while locked, so a guess cannot be confirmed.
    assert (await api_client.post(LOGIN, json=login_body("lock@summan.com"))).status_code == 429


@pytest.mark.asyncio
async def test_lock_expires_and_backoff_doubles_up_to_the_cap(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "backoff@summan.com")
    await _fail(api_client, "backoff@summan.com", 5)
    clock.advance(59)
    assert (await api_client.post(LOGIN, json=login_body("backoff@summan.com"))).status_code == 429
    clock.advance(2)  # 61 s after the 5th failure: the 60 s lock is over
    assert await _fail(api_client, "backoff@summan.com") == [401]  # 6th failure: lock doubles to 120 s
    clock.advance(100)
    assert (await api_client.post(LOGIN, json=login_body("backoff@summan.com"))).status_code == 429
    clock.advance(21)
    delays = []
    for _ in range(8):
        assert await _fail(api_client, "backoff@summan.com") == [401]
        blocked = await api_client.post(LOGIN, json=login_body("backoff@summan.com"))
        assert blocked.status_code == 429
        delays.append(int(blocked.headers["Retry-After"]))
        clock.advance(delays[-1])
    assert delays[:3] == [241, 481, 901]
    assert max(delays) == rate_limit.MAX_LOCKOUT_SECONDS + 1


@pytest.mark.asyncio
async def test_success_clears_the_counter(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "reset@summan.com")
    await _fail(api_client, "reset@summan.com", 4)
    assert (await api_client.post(LOGIN, json=login_body("reset@summan.com"))).status_code == 200
    async with api_session_factory() as session:
        assert (await session.scalars(select(LoginAttempt))).all() == []
    assert await _fail(api_client, "reset@summan.com", 4) == [401] * 4  # a fresh count, not 8


@pytest.mark.asyncio
async def test_failures_are_forgotten_after_the_window(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "window@summan.com")
    await _fail(api_client, "window@summan.com", 4)
    clock.advance(rate_limit.WINDOW_SECONDS + 1)
    assert await _fail(api_client, "window@summan.com", 4) == [401] * 4


@pytest.mark.asyncio
async def test_lock_is_isolated_per_client_address_and_email(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock, api_db_url: str
) -> None:
    from app.main import app

    await add_user(api_session_factory, "iso1@summan.com")
    await add_user(api_session_factory, "iso2@summan.com")
    await _fail(api_client, "iso1@summan.com", 5)
    assert (await api_client.post(LOGIN, json=login_body("iso1@summan.com"))).status_code == 429
    # Same address, another account: unaffected.
    assert (await api_client.post(LOGIN, json=login_body("iso2@summan.com"))).status_code == 200
    # Another address, same account: the per-address pair is not locked, so the right password works.
    other = AsyncClient(transport=ASGITransport(app=app, client=("10.9.8.7", 4321)), base_url="http://test")
    async with other:
        assert (await other.post(LOGIN, json=login_body("iso1@summan.com"))).status_code == 200


@pytest.mark.asyncio
async def test_email_wide_counter_stops_guessing_from_many_addresses(
    api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock, api_db_url: str
) -> None:
    from app.main import app

    await add_user(api_session_factory, "spread@summan.com")
    for index in range(rate_limit.EMAIL_THRESHOLD):
        transport = ASGITransport(app=app, client=(f"10.0.0.{index + 1}", 1000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert await _fail(client, "spread@summan.com") == [401]
    fresh = ASGITransport(app=app, client=("10.0.1.1", 1000))
    async with AsyncClient(transport=fresh, base_url="http://test") as client:
        assert (await client.post(LOGIN, json=login_body("spread@summan.com"))).status_code == 429


@pytest.mark.asyncio
async def test_429_is_identical_for_existing_and_unknown_accounts(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "known@summan.com")
    await _fail(api_client, "known@summan.com", 5)
    await _fail(api_client, "ghost@summan.com", 5)
    known = await api_client.post(LOGIN, json=login_body("known@summan.com"))
    ghost = await api_client.post(LOGIN, json=login_body("ghost@summan.com"))
    assert (known.status_code, known.json(), known.headers["Retry-After"]) == (
        ghost.status_code,
        ghost.json(),
        ghost.headers["Retry-After"],
    )
    assert known.status_code == 429


@pytest.mark.asyncio
async def test_email_case_does_not_evade_the_counter(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await add_user(api_session_factory, "case@summan.com")
    for variant in ["case@summan.com", "CASE@summan.com", "Case@summan.com", "case@SUMMAN.com", "case@summan.com"]:
        assert await _fail(api_client, variant) == [401]
    assert (await api_client.post(LOGIN, json=login_body("CASE@summan.com"))).status_code == 429


@pytest.mark.asyncio
async def test_failures_are_audited_without_password_or_raw_email(
    api_client: AsyncClient, api_session_factory: async_sessionmaker[AsyncSession], clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_user(api_session_factory, "audit@summan.com")
    with caplog.at_level("INFO", logger="sauri.auth"):
        await api_client.post(LOGIN, json=login_body("audit@summan.com", "super-secret-attempt"))
        await api_client.post(LOGIN, json=login_body("nobody@summan.com", "super-secret-attempt"))
    async with api_session_factory() as session:
        logs = (await session.scalars(select(AccessLog))).all()
        stored = (await session.scalars(select(LoginAttempt))).all()
    assert len(logs) == 2 and all(log.result == "denied" for log in logs)
    haystack = " ".join([log.resource for log in logs] + [record.getMessage() for record in caplog.records])
    assert "super-secret-attempt" not in haystack
    assert "audit@summan.com" not in haystack and "nobody@summan.com" not in haystack
    assert rate_limit.email_digest("audit@summan.com") in haystack
    assert all(len(row.key_hash) == 64 for row in stored) and len(stored) == 4  # two keys per distinct email
