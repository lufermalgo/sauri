"""Minimal, deterministic seed of the single administrator account.

NOT an integration with Summan's IdP: it's a minimal store backing the
Authentication_Service until that integration exists (Req. 13.1, 13.2,
13.3). There is no default password: the caller supplies it (see
`app.auth.seed_admin`, which reads it from a private secret file).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.copy.auth_es import ADMIN_NAME
from app.infra.models import User

ADMIN_EMAIL = "admin@sauri.local"

# The meeting features require is_sales=True.
SEED_USERS: list[dict[str, str | bool]] = [
    {
        "email": ADMIN_EMAIL,
        "name": ADMIN_NAME,
        "is_sales": True,
    },
]


async def seed_users(session: AsyncSession, password: str) -> list[User]:
    """Inserts the minimal user seed if it doesn't already exist (idempotent)."""
    created: list[User] = []
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
    await session.flush()
    return created
