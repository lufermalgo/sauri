"""Authentication_Service — login and logout (chrome-side-panel, Req. 13).

Validates the Sales_User's credentials against the minimal `User` store and issues the User_Session
(JWT) with `create_token`. Not an integration with Summan's IdP.

Hardening (#1069): failed attempts are rate limited (`app.auth.rate_limit`), an unknown account costs
the same hashing work as a known one, hashes are upgraded to Argon2id on success, and logout revokes
every session of the user by bumping `users.token_version`.

The Chrome extension may also ask for a refresh token (#1123): `POST /login` with `client="extension"`
returns one, `POST /refresh` rotates it into a new access token, and logout revokes it. The portal never
receives one.

Requirements: 13.2, 13.3, 13.5
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import refresh as refresh_tokens
from app.auth.dependencies import get_current_user
from app.auth.local import local_mode, local_token
from app.auth.passwords import hash_password, needs_rehash, verify_dummy_password, verify_password
from app.auth.rate_limit import (
    clear_failures,
    email_digest,
    lockout_remaining,
    record_failure,
    record_refresh_failure,
    refresh_lockout_remaining,
)
from app.auth.schemas import AuthenticatedUser, LoginRequest, LoginResponse, RefreshRequest
from app.auth.token import create_token, get_jwt_secret
from app.infra.database import create_engine, create_session_factory
from app.infra.models import AccessLog, User

logger = logging.getLogger("sauri.auth")

_EXPIRES_MINUTES = 60
_LOGIN_RESOURCE = "POST /api/v1/auth/login"
_REFRESH_RESOURCE = "POST /api/v1/auth/refresh"


@asynccontextmanager
async def _startup_checks(_: FastAPI) -> AsyncIterator[None]:
    """Validate the configured mode's credential without revealing its value."""
    if local_mode():
        local_token()
    else:
        get_jwt_secret()
    yield


class _SanitizedValidationRoute(APIRoute):
    """Return 422 without the rejected input, so a malformed login never echoes the password."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            if local_mode():
                return JSONResponse(status_code=404, content={"detail": "local_password_auth_disabled"})
            try:
                return await original(request)
            except RequestValidationError as exc:
                detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": detail})

        return handler


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    route_class=_SanitizedValidationRoute,
    lifespan=_startup_checks,
)


def _too_many_attempts(retry_after: int) -> HTTPException:
    # Same body for every locked key: it does not say which key, or whether the account exists.
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts",
        headers={"Retry-After": str(retry_after)},
    )


async def _register_failure(session: AsyncSession, user: User | None, client_ip: str, email: str) -> None:
    locked_for = await record_failure(session, client_ip, email)
    digest = email_digest(email)
    session.add(
        AccessLog(
            id=str(uuid.uuid4()),
            user_id=user.id if user is not None else None,
            resource=f"{_LOGIN_RESOURCE} email_sha256={digest} ip={client_ip}"[:512],
            result="denied",
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    logger.warning("login failed email_sha256=%s ip=%s", digest, client_ip)
    if locked_for:
        logger.warning("login lockout email_sha256=%s ip=%s seconds=%d", digest, client_ip, locked_for)


@router.post("/login", response_model=LoginResponse, response_model_exclude_none=True)
async def login(login_request: LoginRequest, request: Request) -> LoginResponse:
    """Validates credentials and issues a JWT (Req. 13.2, 13.3).

    401 if the email doesn't exist or the password is wrong — the response doesn't distinguish between
    the two cases, nor does its timing. 429 with `Retry-After` while the attempt is rate limited.
    """
    client_ip = request.client.host if request.client else "unknown"
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            retry_after = await lockout_remaining(session, client_ip, login_request.email)
            if retry_after:
                raise _too_many_attempts(retry_after)

            stmt = select(User).where(User.email == login_request.email)
            user = (await session.execute(stmt)).scalar_one_or_none()

            if user is None:
                await asyncio.to_thread(verify_dummy_password, login_request.password)
                valid = False
            else:
                valid = await asyncio.to_thread(verify_password, login_request.password, user.password_hash)

            if user is None or not valid:
                await _register_failure(session, user, client_ip, login_request.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            if needs_rehash(user.password_hash):
                user.password_hash = await asyncio.to_thread(hash_password, login_request.password)
            await clear_failures(session, client_ip, login_request.email)
            await session.commit()

            token = create_token(
                user_id=user.id,
                email=user.email,
                name=user.name,
                is_sales=user.is_sales,
                expires_minutes=_EXPIRES_MINUTES,
                token_version=user.token_version,
            )
            response = LoginResponse(
                access_token=token,
                token_type="bearer",
                expires_in=_EXPIRES_MINUTES * 60,
            )
            if login_request.client == "extension":
                issued = await refresh_tokens.start_family(session, user)
                await session.commit()
                response.refresh_token = issued.token
                response.refresh_expires_in = issued.expires_in
            return response
    finally:
        await engine.dispose()


def _too_many_refreshes(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many refresh attempts",
        headers={"Retry-After": str(retry_after)},
    )


async def _reject_refresh(session: AsyncSession, client_ip: str) -> HTTPException:
    """Count the failure, audit it and build the one 401 every rejected token gets (no reason, no hint)."""
    locked_for = await record_refresh_failure(session, client_ip)
    session.add(
        AccessLog(
            id=str(uuid.uuid4()),
            user_id=None,
            resource=f"{_REFRESH_RESOURCE} ip={client_ip}"[:512],
            result="denied",
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    logger.warning("refresh rejected ip=%s", client_ip)
    if locked_for:
        logger.warning("refresh lockout ip=%s seconds=%d", client_ip, locked_for)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh(refresh_request: RefreshRequest, request: Request) -> LoginResponse:
    """Exchanges a refresh token for a new access token and a new refresh token (#1123).

    The presented token is retired. A token that was already retired revokes its whole family.
    Every rejection (unknown, expired, revoked, reused, account gone, version changed) is the same 401;
    429 with `Retry-After` while this address is rate limited.
    """
    client_ip = request.client.host if request.client else "unknown"
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            retry_after = await refresh_lockout_remaining(session, client_ip)
            if retry_after:
                raise _too_many_refreshes(retry_after)

            result = await refresh_tokens.rotate(session, refresh_request.refresh_token)
            if result.user is None or result.issued is None:
                if result.reused_family_id is not None:
                    logger.warning("refresh token reuse, family revoked family=%s", result.reused_family_id)
                raise await _reject_refresh(session, client_ip)
            await session.commit()

            user = result.user
            token = create_token(
                user_id=user.id,
                email=user.email,
                name=user.name,
                is_sales=user.is_sales,
                expires_minutes=_EXPIRES_MINUTES,
                token_version=user.token_version,
            )
            return LoginResponse(
                access_token=token,
                token_type="bearer",
                expires_in=_EXPIRES_MINUTES * 60,
                refresh_token=result.issued.token,
                refresh_expires_in=result.issued.expires_in,
            )
    finally:
        await engine.dispose()


@router.post("/refresh/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_refresh(refresh_request: RefreshRequest) -> Response:
    """Ends the session of a refresh token (the extension's sign-out when its access token has expired).

    Always 204: it does not say whether the token existed. Knowing the token is the only credential needed,
    which is also what it takes to use it.
    """
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            await refresh_tokens.revoke_by_token(session, refresh_request.refresh_token)
            await session.commit()
    finally:
        await engine.dispose()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> Response:
    """Revokes every session of the caller: access tokens issued before now stop validating, and so do
    all of the caller's refresh tokens."""
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(token_version=User.token_version + 1)
            )
            await refresh_tokens.revoke_user_tokens(session, user.id)
            await session.commit()
    finally:
        await engine.dispose()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
