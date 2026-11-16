"""Creation and validation of the User_Session JWT (HS256, PyJWT).

The signing secret is mandatory: it comes from the file named by ``JWT_SECRET_FILE`` (preferred) or from
``JWT_SECRET`` and must hold at least 32 bytes. There is no built-in fallback. Only the explicit test
environment (``APP_ENV=test``) may run without one, and it then gets a random per-process secret.
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.infra.secrets import read_secret

JWT_ALGORITHM = "HS256"
MIN_SECRET_BYTES = 32

_test_secret = secrets.token_hex(32)


class JwtConfigurationError(RuntimeError):
    """The signing secret is missing or too short. Messages never contain the secret."""


def get_jwt_secret() -> str:
    """Return the signing secret or raise ``JwtConfigurationError`` (never returns a weak value)."""
    secret = read_secret("JWT_SECRET_FILE", "JWT_SECRET")
    if secret is not None and len(secret.encode("utf-8")) >= MIN_SECRET_BYTES:
        return secret
    if os.environ.get("APP_ENV", "").lower() == "test":
        return _test_secret
    reason = "is not set" if secret is None else f"is shorter than {MIN_SECRET_BYTES} bytes"
    raise JwtConfigurationError(f"The JWT signing secret (JWT_SECRET_FILE or JWT_SECRET) {reason}")


def create_token(
    user_id: str,
    email: str,
    name: str,
    is_sales: bool,
    expires_minutes: int = 60,
    token_version: int = 0,
) -> str:
    """Create a signed JWT for the user.

    ``is_sales`` and the profile claims are informational: authorization reads the role from the
    database on every request. ``token_version`` (claim ``tv``) must match ``users.token_version``
    for the token to be accepted, which is how logout revokes every session of a user.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "name": name,
        "is_sales": is_sales,
        "tv": token_version,
        "jti": uuid.uuid4().hex,
        "exp": now + timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Validate signature, algorithm and expiry; raise ``jwt.PyJWTError`` otherwise."""
    jwt.get_unverified_header(token)  # Malformed input is a token error, whatever the configuration.
    payload: dict[str, Any] = jwt.decode(
        token,
        get_jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    return payload
