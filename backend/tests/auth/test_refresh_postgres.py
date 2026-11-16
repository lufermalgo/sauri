"""Concurrent use of one refresh token on real PostgreSQL: exactly one winner, then the family is revoked (#1123)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.auth import refresh
from app.infra.models import AuthRefreshToken, User

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
async def factory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_refresh_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    target = url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)
    engine = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        monkeypatch.setenv("DATABASE_URL", target)
        await asyncio.to_thread(command.upgrade, Config(str(BACKEND / "alembic.ini")), "head")
        engine = create_async_engine(target, poolclass=NullPool)
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()


async def test_two_simultaneous_refreshes_with_one_token_let_exactly_one_through(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session, session.begin():
        user = User(
            id=str(uuid.uuid4()), email="race@example.test", name="S", password_hash="x", created_at=datetime.now(UTC)
        )
        session.add(user)
    async with factory() as session, session.begin():
        issued = await refresh.start_family(session, user)

    async def attempt() -> bool:
        async with factory() as session:
            result = await refresh.rotate(session, issued.token)
            await session.commit()
            return result.issued is not None

    outcomes = await asyncio.gather(attempt(), attempt())
    assert sorted(outcomes) == [False, True]  # The loser sees a rotated token: replay, the family is revoked.

    async with factory() as session:
        rows = list((await session.scalars(select(AuthRefreshToken))).all())
    assert len(rows) == 2 and all(row.revoked_at is not None for row in rows)
