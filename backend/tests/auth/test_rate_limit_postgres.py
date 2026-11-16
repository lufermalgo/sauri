"""Rate-limit counters stay exact under concurrent failures on real PostgreSQL (#1069)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.auth import rate_limit
from app.infra.models import LoginAttempt

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
async def factory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_ratelimit_{uuid.uuid4().hex}"
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


async def test_concurrent_failures_are_all_counted_and_lock_the_key(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def fail_once() -> None:
        async with factory() as session:
            await rate_limit.record_failure(session, "10.1.1.1", "race@summan.com")
            await session.commit()

    await asyncio.gather(*(fail_once() for _ in range(rate_limit.PAIR_THRESHOLD)))

    async with factory() as session:
        rows = {row.scope: row for row in (await session.scalars(select(LoginAttempt))).all()}
        assert rows[rate_limit.SCOPE_PAIR].failures == rate_limit.PAIR_THRESHOLD
        assert rows[rate_limit.SCOPE_EMAIL].failures == rate_limit.PAIR_THRESHOLD
        assert rows[rate_limit.SCOPE_PAIR].locked_until is not None
        assert await rate_limit.lockout_remaining(session, "10.1.1.1", "race@summan.com") > 0
        assert await rate_limit.lockout_remaining(session, "10.2.2.2", "race@summan.com") == 0
        await rate_limit.clear_failures(session, "10.1.1.1", "race@summan.com")
        await session.commit()
        assert (await session.scalars(select(LoginAttempt))).all() == []
