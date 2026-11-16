"""Migration 021 adds the thumbnail columns and reverses cleanly."""

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
REVISION = "022_recording_thumbnail"
PARENT = "021_default_summary_legacy_default"


def test_revision_chains_after_the_summary_structure_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["029_meeting_recorded_at"]  # The recording-date revision follows.
    assert script.get_revision("023_summary_request_timestamps").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT


@pytest.mark.asyncio
async def test_postgres_upgrade_downgrade_upgrade_keeps_existing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_thumbnail_{uuid4().hex}"
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
            "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
            "VALUES ('m-1', 'manual', 'completed', 'owner', now())"
        )
        await connection.execute(
            "INSERT INTO session_recordings (id, meeting_id, idempotency_key, capture_origin, audio_ref, "
            "duration_seconds, interrupted, finished_at, video_presence) "
            "VALUES ('r-1', 'm-1', 'k-1', 'web_upload', 'recordings/m-1/a/audio', 0, false, now(), 'muxed')"
        )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        columns = {
            record["column_name"]: record["is_nullable"]
            for record in await connection.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'session_recordings' AND column_name LIKE 'thumbnail_%'"
            )
        }
        assert columns == {"thumbnail_ref": "YES", "thumbnail_state": "YES"}
        # Existing recordings start as "not attempted" so the worker backfills them.
        assert await connection.fetchrow(
            "SELECT thumbnail_ref, thumbnail_state FROM session_recordings WHERE id = 'r-1'"
        ) == (None, None)
        await connection.execute("UPDATE session_recordings SET thumbnail_state = 'ready' WHERE id = 'r-1'")
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute("UPDATE session_recordings SET thumbnail_state = 'bogus' WHERE id = 'r-1'")

        await asyncio.to_thread(command.downgrade, config, PARENT)
        assert not await connection.fetch(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'session_recordings' AND column_name LIKE 'thumbnail_%'"
        )
        assert await connection.fetchval("SELECT count(*) FROM session_recordings") == 1

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
