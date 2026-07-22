"""Minimal, deterministic seed of authorized sales Users.

NOT an integration with Summan's IdP: it's a minimal store backing the
Authentication_Service until that integration exists (Req. 13.1, 13.2,
13.3). The default password can be overridden via the SAURI_SEED_PASSWORD
environment variable (development/test only).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.infra.models import User

_DEFAULT_SEED_PASSWORD = "sauri-dev-2026"


def _seed_password() -> str:
    return os.getenv("SAURI_SEED_PASSWORD", _DEFAULT_SEED_PASSWORD)


SEED_USERS: list[dict[str, str | bool]] = [
    {
        "email": "comercial1@summan.com",
        "name": "Comercial Summan Uno",
        "is_sales": True,
    },
    {
        "email": "comercial2@summan.com",
        "name": "Comercial Summan Dos",
        "is_sales": True,
    },
]


async def seed_users(session: AsyncSession) -> list[User]:
    """Inserts the minimal user seed if it doesn't already exist (idempotent)."""
    created: list[User] = []
    password = _seed_password()
    for data in SEED_USERS:
        stmt = select(User).where(User.email == data["email"])
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            continue
        user = User(
            id=str(uuid.uuid4()),
            email=str(data["email"]),
            name=str(data["name"]),
            password_hash=hash_password(password),
            is_sales=bool(data["is_sales"]),
            created_at=datetime.now(UTC),
        )
        session.add(user)
        created.append(user)
    return created
