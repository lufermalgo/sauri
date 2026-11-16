"""#1053: migration 024 on a disposable PostgreSQL, up, down and up again."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from alembic import command

BACKEND = Path(__file__).parents[2]
REVISION = "024_regeneration_operations"
PARENT = "023_summary_request_timestamps"


def test_revision_is_the_single_head_after_summary_timestamps() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["029_meeting_recorded_at"]  # The recording-date revision follows.
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32) unless widened


async def test_upgrade_creates_the_audit_table_and_downgrade_removes_only_it(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_regen_{uuid4().hex}"
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
            "VALUES ('u', 'u@example.test', 'S', 'x', true, now())")
        await connection.execute(
            "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
            "VALUES ('m', 'manual', 'completed', 'u', now())")

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        insert = (
            "INSERT INTO regeneration_operations (id, meeting_id, stage, status, requested_by, requested_at) "
            "VALUES ($1, 'm', $2, $3, 'u', now())"
        )
        await connection.execute(insert, "op-1", "speakers", "running")
        with pytest.raises(asyncpg.UniqueViolationError):  # one active operation per meeting
            await connection.execute(insert, "op-2", "summary", "accepted")
        await connection.execute(insert, "op-3", "summary", "failed")  # settled ones are unlimited
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(insert, "op-4", "audio", "failed")
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(insert, "op-5", "summary", "paused")
        assert await connection.fetchval("SELECT cascade FROM regeneration_operations WHERE id = 'op-1'") is False

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        assert await connection.fetchval("SELECT to_regclass('regeneration_operations')") is None
        assert await connection.fetchval("SELECT count(*) FROM meetings") == 1  # nothing else was touched

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT count(*) FROM regeneration_operations") == 0
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
