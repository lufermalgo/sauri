"""Migration 023 adds the request lifecycle timestamps, backfills them and reverses cleanly."""

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
REVISION = "023_summary_request_timestamps"
PARENT = "022_recording_thumbnail"


def test_revision_chain_keeps_a_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["025_auth_hardening"]  # The regeneration and auth revisions follow.
    assert script.get_revision("024_regeneration_operations").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32) unless widened


@pytest.mark.asyncio
async def test_postgres_backfills_requested_at_and_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_sumstamps_{uuid4().hex}"
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
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('t-1', 'm-1', 'es', 'synthetic', false, now())"
        )
        insert = (
            "INSERT INTO summary_request_outbox (event_id, meeting_id, transcript_id, template_id, "
            "template_version, instructions_snapshot, generation, status, delivered_at) "
        )
        await connection.execute("INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
                                 "VALUES ('owner', 'o@example.test', 'Synthetic', 'x', true, now())")
        await connection.execute(
            "INSERT INTO summary_templates (id, owner_user_id, name, version, instructions, created_at, updated_at) "
            "VALUES ('tpl', 'owner', 'Synthetic', 1, 'i', now(), now())"
        )
        await connection.execute(insert + "VALUES ('e-delivered', 'm-1', 't-1', 'tpl', 1, 'i', 1, 'succeeded', "
                                 "'2026-01-02 03:04:05+00')")
        await connection.execute(insert + "VALUES ('e-undelivered', 'm-1', 't-1', 'tpl', 1, 'i', 2, 'pending', NULL)")

        await asyncio.to_thread(command.upgrade, config, REVISION)
        columns = {
            record["column_name"]: record["is_nullable"]
            for record in await connection.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'summary_request_outbox' "
                "AND column_name IN ('requested_at', 'started_at', 'finished_at')"
            )
        }
        assert columns == {"requested_at": "YES", "started_at": "YES", "finished_at": "YES"}
        rows = {
            record["event_id"]: record
            for record in await connection.fetch(
                "SELECT event_id, requested_at, started_at, finished_at, delivered_at FROM summary_request_outbox"
            )
        }
        assert rows["e-delivered"]["requested_at"] == rows["e-delivered"]["delivered_at"]  # backfilled
        assert rows["e-undelivered"]["requested_at"] is None
        assert all(r["started_at"] is None and r["finished_at"] is None for r in rows.values())

        await asyncio.to_thread(command.downgrade, config, PARENT)
        assert not await connection.fetch(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'summary_request_outbox' "
            "AND column_name IN ('requested_at', 'started_at', 'finished_at')"
        )
        assert await connection.fetchval("SELECT count(*) FROM summary_request_outbox") == 2

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        assert await connection.fetchval(
            "SELECT requested_at FROM summary_request_outbox WHERE event_id = 'e-delivered'"
        ) is not None
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
