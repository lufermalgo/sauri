"""Rotating refresh tokens for the Chrome extension session (#1123).

A refresh token is 256 random bits, shown once to the client; only its SHA-256 digest is stored. Each
login of the extension starts a *family*. Every refresh retires the presented token (``rotated_at``) and
issues a successor in the same family, so a family always has at most one usable token. Presenting a token
that was already rotated means two parties hold it, so the whole family is revoked.

Lifetimes (owner review pending): a token stays usable ``REFRESH_IDLE_DAYS`` after it was issued, and the
family never outlives ``REFRESH_ABSOLUTE_DAYS`` from the login that created it, however often it is used.
Nothing here ever logs or returns a stored digest; callers must not log the token either.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import AuthRefreshToken, User

REFRESH_IDLE_DAYS = 30
REFRESH_ABSOLUTE_DAYS = 90
# Spent rows are kept this long so a replayed token is still recognized as reuse, then pruned.
RETENTION_DAYS = 7


@dataclass(frozen=True)
class IssuedRefreshToken:
    """The one moment the plain token exists: hand it to the client, never store or log it."""

    token: str
    expires_in: int  # seconds until this token can no longer be used


def utcnow() -> datetime:
    """Clock used by the refresh service; tests replace it to advance time."""
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _new_row(
    user_id: str, token_version: int, family_id: str, absolute_expires_at: datetime, now: datetime
) -> tuple[AuthRefreshToken, IssuedRefreshToken]:
    token = secrets.token_urlsafe(32)  # 256 bits
    idle_expires_at = min(now + timedelta(days=REFRESH_IDLE_DAYS), absolute_expires_at)
    row = AuthRefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_token(token),
        token_version=token_version,
        issued_at=now,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )
    return row, IssuedRefreshToken(token=token, expires_in=int((idle_expires_at - now).total_seconds()))


async def start_family(session: AsyncSession, user: User) -> IssuedRefreshToken:
    """Issue the first refresh token of a new family (a fresh sign-in). The caller commits."""
    now = utcnow()
    await _prune(session, user.id, now)
    row, issued = _new_row(
        user.id, user.token_version, str(uuid.uuid4()), now + timedelta(days=REFRESH_ABSOLUTE_DAYS), now
    )
    session.add(row)
    return issued


async def _prune(session: AsyncSession, user_id: str, now: datetime) -> None:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    await session.execute(
        delete(AuthRefreshToken).where(
            AuthRefreshToken.user_id == user_id,
            or_(
                AuthRefreshToken.rotated_at < cutoff,
                AuthRefreshToken.revoked_at < cutoff,
                AuthRefreshToken.absolute_expires_at < cutoff,
            ),
        ),
        execution_options={"synchronize_session": False},
    )


async def revoke_family(session: AsyncSession, family_id: str) -> None:
    """Make every token of the family unusable. The caller commits."""
    await session.execute(
        update(AuthRefreshToken)
        .where(AuthRefreshToken.family_id == family_id, AuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
        .execution_options(synchronize_session=False)
    )


async def revoke_user_tokens(session: AsyncSession, user_id: str) -> None:
    """Make every refresh token of the user unusable (logout, password change). The caller commits."""
    await session.execute(
        update(AuthRefreshToken)
        .where(AuthRefreshToken.user_id == user_id, AuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
        .execution_options(synchronize_session=False)
    )


async def revoke_by_token(session: AsyncSession, token: str) -> None:
    """Revoke the family of the presented token; an unknown token is ignored. The caller commits."""
    family_id = (
        await session.execute(
            select(AuthRefreshToken.family_id).where(AuthRefreshToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if family_id is not None:
        await revoke_family(session, family_id)


@dataclass(frozen=True)
class RotationResult:
    """Outcome of ``rotate``: ``user`` and ``issued`` are set only when the token was accepted."""

    user: User | None
    issued: IssuedRefreshToken | None
    #: Set when the rejection was a replay of a rotated token (the family id is not secret).
    reused_family_id: str | None = None


async def rotate(session: AsyncSession, token: str) -> RotationResult:
    """Validate and retire ``token``, issuing its successor. The caller commits in every case.

    Rejected when the digest is unknown, the token was already rotated (reuse: the family is revoked),
    it is revoked or past either expiry, the account is gone, or ``users.token_version`` no longer
    matches the version the family was issued under (that family is revoked too).
    """
    now = utcnow()
    row = (
        await session.execute(
            select(AuthRefreshToken).where(AuthRefreshToken.token_hash == hash_token(token)).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return RotationResult(user=None, issued=None)
    if row.rotated_at is not None:
        # A rotated token comes back only if it was copied: end the family, whoever holds the newer token.
        await revoke_family(session, row.family_id)
        return RotationResult(user=None, issued=None, reused_family_id=row.family_id)
    if (
        row.revoked_at is not None
        or _aware(row.idle_expires_at) <= now
        or _aware(row.absolute_expires_at) <= now
    ):
        return RotationResult(user=None, issued=None)
    user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or user.token_version != row.token_version:
        await revoke_family(session, row.family_id)
        return RotationResult(user=None, issued=None)

    row.rotated_at = now
    row.last_used_at = now
    successor, issued = _new_row(user.id, user.token_version, row.family_id, _aware(row.absolute_expires_at), now)
    session.add(successor)
    await _prune(session, user.id, now)
    return RotationResult(user=user, issued=issued)
