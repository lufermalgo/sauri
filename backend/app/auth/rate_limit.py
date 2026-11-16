"""Login rate limiting with exponential backoff, stored in the `login_attempts` table.

Why a table and not process memory: the counters survive an API restart and stay correct if more than
one API process ever runs, and the state is two small rows per client. Rows are keyed by SHA-256
digests, so neither emails nor addresses are stored.

Two counters apply to every attempt, whether or not the account exists:

* ``ip_email``: client address + normalized email, so one person mistyping does not lock another.
  Locks after ``PAIR_THRESHOLD`` consecutive failures.
* ``email``: normalized email alone, a higher bar that still stops a distributed guesser. It is high
  on purpose: it lets an attacker lock an account for at most ``MAX_LOCKOUT_SECONDS`` at a time.

The refresh endpoint (#1123) uses a third counter, ``refresh_ip``, keyed on the client address alone
(there is no email in a refresh request), with the same lock, backoff and forgetting rules.

The failure that reaches the threshold locks the key for ``BASE_LOCKOUT_SECONDS``; every further failure
doubles the lock up to ``MAX_LOCKOUT_SECONDS``. A key forgets its failures after ``WINDOW_SECONDS``
without a new failure, and a successful login clears both keys.

Known limit: the client address is the direct peer. Behind a reverse proxy every client shares the
proxy address until trusted forwarding is configured, so the pair counter then behaves like the email one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import LoginAttempt

SCOPE_PAIR = "ip_email"
SCOPE_EMAIL = "email"
SCOPE_REFRESH = "refresh_ip"

PAIR_THRESHOLD = 5
EMAIL_THRESHOLD = 20
# Refresh failures are rare for a well-behaved client (it drops a rejected token), so a sustained run
# from one address is a guesser or a replay. The bar is higher than for passwords because every
# extension behind one proxy address shares it.
REFRESH_THRESHOLD = 10
BASE_LOCKOUT_SECONDS = 60
MAX_LOCKOUT_SECONDS = 15 * 60
WINDOW_SECONDS = 30 * 60
_MAX_DOUBLINGS = 10


def utcnow() -> datetime:
    """Clock used by the limiter; tests replace it to advance time."""
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_digest(email: str) -> str:
    """Short, stable digest for logs."""
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class _Key:
    scope: str
    key_hash: str
    threshold: int


def _keys(client_ip: str, email: str) -> list[_Key]:
    normalized = normalize_email(email)
    pair = hashlib.sha256(f"{client_ip}|{normalized}".encode()).hexdigest()
    alone = hashlib.sha256(normalized.encode()).hexdigest()
    return [_Key(SCOPE_PAIR, pair, PAIR_THRESHOLD), _Key(SCOPE_EMAIL, alone, EMAIL_THRESHOLD)]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _refresh_keys(client_ip: str) -> list[_Key]:
    return [_Key(SCOPE_REFRESH, hashlib.sha256(f"refresh|{client_ip}".encode()).hexdigest(), REFRESH_THRESHOLD)]


async def lockout_remaining(session: AsyncSession, client_ip: str, email: str) -> int:
    """Seconds left on the longest active lock for this attempt, 0 when it may proceed."""
    return await _lockout_remaining(session, _keys(client_ip, email))


async def refresh_lockout_remaining(session: AsyncSession, client_ip: str) -> int:
    """Seconds left on the refresh lock for this client address, 0 when it may proceed."""
    return await _lockout_remaining(session, _refresh_keys(client_ip))


async def _lockout_remaining(session: AsyncSession, keys: list[_Key]) -> int:
    now = utcnow()
    rows = (
        await session.execute(
            select(LoginAttempt).where(LoginAttempt.key_hash.in_([key.key_hash for key in keys]))
        )
    ).scalars()
    remaining = 0.0
    for row in rows:
        if row.locked_until is not None:
            remaining = max(remaining, (_aware(row.locked_until) - now).total_seconds())
    return int(remaining) + 1 if remaining > 0 else 0


async def record_failure(session: AsyncSession, client_ip: str, email: str) -> int:
    """Count a failed attempt on both keys; return the lock (seconds) it started, 0 if none."""
    return await _record_failure(session, _keys(client_ip, email))


async def record_refresh_failure(session: AsyncSession, client_ip: str) -> int:
    """Count a rejected refresh attempt for this address; return the lock (seconds) it started, 0 if none."""
    return await _record_failure(session, _refresh_keys(client_ip))


async def _record_failure(session: AsyncSession, keys: list[_Key]) -> int:
    now = utcnow()
    longest = 0
    for key in keys:
        await _ensure_row(session, key, now)
        row = (
            await session.execute(
                select(LoginAttempt)
                .where(LoginAttempt.scope == key.scope, LoginAttempt.key_hash == key.key_hash)
                .with_for_update()
            )
        ).scalar_one()
        if now - _aware(row.last_failure_at) > timedelta(seconds=WINDOW_SECONDS):
            row.failures = 0
            row.locked_until = None
        row.failures += 1
        row.last_failure_at = now
        if row.failures >= key.threshold:
            doublings = min(row.failures - key.threshold, _MAX_DOUBLINGS)
            seconds = min(BASE_LOCKOUT_SECONDS * 2**doublings, MAX_LOCKOUT_SECONDS)
            row.locked_until = now + timedelta(seconds=seconds)
            longest = max(longest, seconds)
    await session.flush()
    return longest


async def clear_failures(session: AsyncSession, client_ip: str, email: str) -> None:
    """Forget the counters after a successful login."""
    for key in _keys(client_ip, email):
        await session.execute(
            delete(LoginAttempt).where(LoginAttempt.scope == key.scope, LoginAttempt.key_hash == key.key_hash)
        )


async def _ensure_row(session: AsyncSession, key: _Key, now: datetime) -> None:
    """Create the counter row if missing; safe when two requests race for the same key."""
    values = {"scope": key.scope, "key_hash": key.key_hash, "failures": 0, "last_failure_at": now}
    dialect = session.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    await session.execute(insert(LoginAttempt).values(values).on_conflict_do_nothing())
