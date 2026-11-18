"""FastAPI dependencies for JWT authentication."""

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.local import local_mode
from app.auth.schemas import AuthenticatedUser
from app.auth.token import decode_token
from app.infra.database import create_engine, create_session_factory
from app.infra.models import User

_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)

_DEV_USER = AuthenticatedUser(
    id="dev-user-00000000",
    email="dev@sauri.local",
    name="Developer (auth disabled)",
    is_sales=True,
)


def _bypass_active() -> bool:
    """Determines whether the AUTH_DISABLED bypass is active.

    Restricted to the test environment (Req. 13.1, 13.4): with the
    addition of `POST /api/v1/auth/login` (chrome-side-panel), the
    development bypass is retired outside automated tests; endpoints
    require a real JWT issued by the Authentication_Service. It's kept
    only for test (`APP_ENV=test`) where other modules still use it as
    a shortcut.
    """
    auth_disabled = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
    app_env = os.getenv("APP_ENV", "").lower()
    return auth_disabled and app_env == "test"


def _test_environment() -> bool:
    return os.getenv("APP_ENV", "").lower() == "test"


def _user_from_claims(sub: str, payload: dict[str, Any]) -> AuthenticatedUser:
    """Test environment only: tokens for users without a row are trusted on their claims.

    Gated like the AUTH_DISABLED bypass (`APP_ENV=test`), so existing route tests that mint tokens
    for synthetic users keep working. Any other environment rejects a token whose account is missing.
    """
    email, name, is_sales = payload.get("email"), payload.get("name"), payload.get("is_sales")
    if not isinstance(email, str) or not isinstance(name, str) or not isinstance(is_sales, bool):
        raise _unauthorized("Token with incomplete claims")
    return AuthenticatedUser(id=sub, email=email, name=name, is_sales=is_sales)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _load_account(user_id: str) -> User | None:
    """Current account row; the database, not the token, is the source of truth for role and revocation."""
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            return (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    finally:
        await engine.dispose()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> AuthenticatedUser:
    """Validates the JWT and the account it names against the database.

    The token must carry a valid signature and expiry, the account must still exist, and the token's
    `tv` claim must equal `users.token_version` (logout bumps it). Tokens without `tv`, issued before
    revocation existed, count as version 0. `email`, `name` and `is_sales` come from the account row,
    so a role change applies to existing tokens on the next request.

    Raises:
        HTTPException 401: if the token is missing, invalid, expired or revoked.
    """
    if local_mode():
        user_id = os.environ.get("SAURI_LOCAL_USER_ID", "")
        account = await _load_account(user_id) if user_id else None
        if account is None:
            raise HTTPException(status_code=500, detail="local_user_missing")
        return AuthenticatedUser(id=account.id, email=account.email, name=account.name, is_sales=account.is_sales)

    # Bypass only in the test environment (AUTH_DISABLED=1 and APP_ENV=test), Req. 13.1, 13.4
    if _bypass_active():
        return _DEV_USER

    if credentials is None:
        raise _unauthorized("Authentication token required")

    try:
        payload: dict[str, Any] = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    sub = payload.get("sub")
    token_version = payload.get("tv", 0)
    if not isinstance(sub, str) or not sub or not isinstance(token_version, int):
        raise _unauthorized("Token with incomplete claims")

    account = await _load_account(sub)
    if account is None:
        if _test_environment():
            return _user_from_claims(sub, payload)
        raise _unauthorized("Invalid or expired token")
    if account.token_version != token_version:
        raise _unauthorized("Invalid or expired token")

    return AuthenticatedUser(
        id=account.id,
        email=account.email,
        name=account.name,
        is_sales=account.is_sales,
    )
