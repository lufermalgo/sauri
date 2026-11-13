"""Regression for the two 014 migrations on the stacked speaker-review branch."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SUMMARIES = "014_meeting_summaries_templates"
PROCESSING = "014_processing_revisions"


def test_both_014_migrations_form_one_head() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    assert script.get_heads() == [PROCESSING]
    assert script.get_revision(PROCESSING).down_revision == SUMMARIES


@pytest.mark.asyncio
async def test_upgrade_from_existing_summaries_preserves_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never connect to a shared DB: create and remove our own database."""
    admin_url = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("requires isolated PostgreSQL admin URL")
    url = make_url(admin_url)
    if url.host not in {"127.0.0.1", "localhost"} or not url.port or url.port < 55000:
        pytest.fail("requires a local high-port isolated PostgreSQL server")
    name = f"sauri_migration_qa_{uuid4().hex}"
    options = dict(
        user=url.username or "",
        password=url.password or "",
        host=url.host,
        port=url.port,
        database=url.database or "postgres",
    )
    admin = await asyncpg.connect(**options)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        monkeypatch.setenv("DATABASE_URL", url.set(database=name).render_as_string(hide_password=False))
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, SUMMARIES)
        connection = await asyncpg.connect(**(options | {"database": name}))
        try:
            await connection.execute(
                "INSERT INTO users(id,email,name,password_hash) "
                "VALUES ('synthetic-owner','synthetic@example.invalid','Synthetic','not-a-real-password')"
            )
            await connection.execute(
                "INSERT INTO template_categories(id,owner_user_id,name,created_at) "
                "VALUES ('synthetic-category','synthetic-owner','Existing',now())"
            )
        finally:
            await connection.close()
        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(**(options | {"database": name}))
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == PROCESSING
            assert (
                await connection.fetchval("SELECT name FROM template_categories WHERE id='synthetic-category'")
                == "Existing"
            )
            assert (
                await connection.fetchval("SELECT to_regclass('public.processing_revisions')") == "processing_revisions"
            )
            assert (
                await connection.fetchval("SELECT to_regclass('public.recording_processing_states')")
                == "recording_processing_states"
            )
        finally:
            await connection.close()
    finally:
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", name)
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.close()
