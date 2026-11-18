"""Migration 025_auth_hardening: single head, upgrade and downgrade on disposable PostgreSQL (#1069)."""

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
REVISION = "025_auth_hardening"
PARENT = "024_regeneration_operations"


def test_revision_is_the_single_head_and_follows_regeneration_operations() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["030_job_messages"]  # The job queue revision follows.
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32)


async def test_upgrade_and_downgrade_on_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_authmig_{uuid.uuid4().hex}"
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
        await connection.execute(
            "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
            "VALUES ('u', 'u@example.test', 'S', 'pbkdf2_sha256$1$aa$bb', true, now())"
        )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        assert await connection.fetchval("SELECT token_version FROM users WHERE id = 'u'") == 0  # existing rows
        insert = (
            "INSERT INTO login_attempts (scope, key_hash, failures, last_failure_at) "
            "VALUES ('email', 'h', 1, now())"
        )
        await connection.execute(insert)
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(insert)

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        assert await connection.fetchval("SELECT to_regclass('login_attempts')") is None
        columns = await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        )
        assert "token_version" not in {row["column_name"] for row in columns}
        assert await connection.fetchval("SELECT count(*) FROM users") == 1  # nothing else touched

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT token_version FROM users WHERE id = 'u'") == 0
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
