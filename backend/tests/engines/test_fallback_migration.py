"""#1117 migration 027: the fallback reason column, up and down, on a disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.infra.database import Base

BACKEND = Path(__file__).parents[2]
REVISION = "027_engine_fallback_reason"
PARENT = "026_engine_providers"
TABLES = ("transcripts", "diarizations", "meeting_summaries")


@pytest.fixture(autouse=True)
def keep_logging_state() -> Iterator[None]:
    """alembic's env.py reconfigures logging and disables every existing logger; undo it for later tests."""
    root = logging.getLogger()
    root_state = (root.level, list(root.handlers))
    loggers = {
        name: (logger.disabled, logger.level, logger.propagate, list(logger.handlers))
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    yield
    root.setLevel(root_state[0])
    root.handlers[:] = root_state[1]
    for name, (disabled, level, propagate, handlers) in loggers.items():
        logger = logging.getLogger(name)
        logger.disabled, logger.propagate = disabled, propagate
        logger.setLevel(level)
        logger.handlers[:] = handlers


def test_revision_id_fits_alembic_version_column() -> None:
    assert len(REVISION) <= 32


async def test_models_declare_a_nullable_reason_column_without_content() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        columns = await connection.run_sync(
            lambda sync: {
                table: {c["name"]: c for c in inspect(sync).get_columns(table)} for table in TABLES
            }
        )
    await engine.dispose()
    for table in TABLES:
        reason = columns[table]["engine_fallback_reason"]
        assert reason["nullable"] and reason["type"].length == 64  # a class code, not free text


async def test_upgrade_and_downgrade_keep_meeting_data(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_QA_POSTGRES_URL") or os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_engines_mig27_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, PARENT)
        connection = await asyncpg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False))
        await connection.execute(
            "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
            "VALUES ('a', 'a@example.test', 'S', 'x', true, now())"
        )
        await connection.execute(
            "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
            "VALUES ('m', 'manual', 'completed', 'a', now())"
        )
        await connection.execute(
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('t', 'm', 'es', 'whisper.cpp', true, now())"
        )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        for table in TABLES:
            assert await connection.fetchval(f"SELECT count(*) FROM {table} WHERE engine_fallback_reason IS NULL") >= 0
        assert await connection.fetchval("SELECT engine_fallback_reason FROM transcripts WHERE id = 't'") is None
        await connection.execute("UPDATE transcripts SET engine_fallback_reason = 'provider_unavailable'")
        with pytest.raises(asyncpg.StringDataRightTruncationError):
            await connection.execute("UPDATE transcripts SET engine_fallback_reason = $1", "x" * 65)

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        columns = await connection.fetch(
            "SELECT table_name FROM information_schema.columns WHERE column_name = 'engine_fallback_reason'"
        )
        assert columns == []
        assert await connection.fetchval("SELECT count(*) FROM transcripts") == 1  # meeting data survives

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
