"""Authentication_Service — login and logout (chrome-side-panel, Req. 13).

Validates the Sales_User's credentials against the minimal `User` store and issues the User_Session
(JWT) with `create_token`. Not an integration with Summan's IdP.

Hardening (#1069): failed attempts are rate limited (`app.auth.rate_limit`), an unknown account costs
the same hashing work as a known one, hashes are upgraded to Argon2id on success, and logout revokes
every session of the user by bumping `users.token_version`.

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

from app.auth.dependencies import get_current_user
from app.auth.passwords import hash_password, needs_rehash, verify_dummy_password, verify_password
from app.auth.rate_limit import clear_failures, email_digest, lockout_remaining, record_failure
from app.auth.schemas import AuthenticatedUser, LoginRequest, LoginResponse
from app.auth.token import create_token, get_jwt_secret
from app.infra.database import create_engine, create_session_factory
from app.infra.models import AccessLog, User

logger = logging.getLogger("sauri.auth")

_EXPIRES_MINUTES = 60
_LOGIN_RESOURCE = "POST /api/v1/auth/login"


@asynccontextmanager
async def _startup_checks(_: FastAPI) -> AsyncIterator[None]:
    """Refuse to start without a usable JWT signing secret (the message never contains it)."""
    get_jwt_secret()
    yield


class _SanitizedValidationRoute(APIRoute):
    """Return 422 without the rejected input, so a malformed login never echoes the password."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
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


@router.post("/login", response_model=LoginResponse)
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
            return LoginResponse(
                access_token=token,
                token_type="bearer",
                expires_in=_EXPIRES_MINUTES * 60,
            )
    finally:
        await engine.dispose()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> Response:
    """Revokes every session of the caller: tokens issued before now stop validating."""
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(token_version=User.token_version + 1)
            )
            await session.commit()
    finally:
        await engine.dispose()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
