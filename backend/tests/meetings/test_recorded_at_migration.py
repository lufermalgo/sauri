"""Migration 029_meeting_recorded_at: single head, backfill and downgrade on disposable PostgreSQL (#1157)."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from alembic import command

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "029_meeting_recorded_at"
PARENT = "028_auth_refresh_tokens"

INSERT_MEETING = (
    "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
    "VALUES ($1, 'manual', 'completed', 'u', $2)"
)


def test_revision_is_the_single_head_and_follows_the_refresh_tokens() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32)


async def test_upgrade_backfills_existing_rows_and_downgrade_removes_the_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_recordedmig_{uuid.uuid4().hex}"
    plain = url.set(drivername="postgresql")
    admin = await asyncpg.connect(plain.render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, PARENT)
        connection = await asyncpg.connect(plain.set(database=database).render_as_string(hide_password=False))
        received = await connection.fetchval("SELECT TIMESTAMPTZ '2026-02-03 04:05:06+00'")
        await connection.execute(INSERT_MEETING, "old-meeting", received)

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        row = await connection.fetchrow("SELECT recorded_at, recorded_at_source FROM meetings WHERE id = 'old-meeting'")
        assert row is not None
        assert row["recorded_at"] == received  # Nothing can be re-probed in a migration: receipt date it is.
        assert row["recorded_at_source"] == "received"

        columns = {r["column_name"]: (r["data_type"], r["is_nullable"]) for r in await connection.fetch(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'meetings' AND column_name IN ('recorded_at', 'recorded_at_source')"
        )}
        assert columns == {
            "recorded_at": ("timestamp with time zone", "YES"),
            "recorded_at_source": ("character varying", "YES"),
        }
        await connection.execute(INSERT_MEETING, "new-meeting", received)  # Both columns stay optional.

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        assert not await connection.fetch(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'meetings' AND column_name IN ('recorded_at', 'recorded_at_source')"
        )
        assert await connection.fetchval("SELECT count(*) FROM meetings") == 2  # Rows survive the downgrade.

        await asyncio.to_thread(command.upgrade, config, REVISION)  # And it can be applied again.
        kept = await connection.fetchval("SELECT recorded_at_source FROM meetings WHERE id = 'old-meeting'")
        assert kept == "received"
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()
