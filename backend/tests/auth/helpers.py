"""Shared helpers for the authentication tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.passwords import hash_password
from app.infra.models import User

PASSWORD = "synthetic-correct-password"


def legacy_hash(password: str, iterations: int = 260_000) -> str:
    """A hash in the format used before Argon2id (`pbkdf2_sha256$iterations$salt$hash`)."""
    salt = bytes(range(16))
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


async def add_user(
    factory: async_sessionmaker[AsyncSession],
    email: str,
    *,
    password: str = PASSWORD,
    password_hash: str | None = None,
    is_sales: bool = True,
) -> str:
    user_id = str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(
            User(
                id=user_id,
                email=email,
                name="Synthetic",
                password_hash=password_hash if password_hash is not None else hash_password(password),
                is_sales=is_sales,
                created_at=datetime.now(UTC),
            )
        )
    return user_id


async def get_user(factory: async_sessionmaker[AsyncSession], user_id: str) -> Any:
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return user


def login_body(email: str, password: str = PASSWORD) -> dict[str, str]:
    return {"email": email, "password": password}
