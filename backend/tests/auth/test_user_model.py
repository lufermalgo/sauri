"""User model and its Alembic migration (chrome-side-panel, Tarea 13.7).

Validates: Requirements 13.1, 13.2
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import User


@pytest.mark.asyncio
async def test_user_can_be_created_and_read(db_session: AsyncSession):
    user = User(
        id=str(uuid.uuid4()),
        email="comercial@summan.com",
        name="Comercial Uno",
        password_hash="$2b$12$hashfalsoparapruebas",
        is_sales=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()

    retrieved = await db_session.get(User, user.id)
    assert retrieved is not None
    assert retrieved.email == "comercial@summan.com"
    assert retrieved.is_sales is True


@pytest.mark.asyncio
async def test_user_email_is_unique(db_session: AsyncSession):
    email = "duplicado@summan.com"
    db_session.add(
        User(
            id=str(uuid.uuid4()),
            email=email,
            name="Uno",
            password_hash="hash1",
            is_sales=True,
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    db_session.add(
        User(
            id=str(uuid.uuid4()),
            email=email,
            name="Dos",
            password_hash="hash2",
            is_sales=True,
            created_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
