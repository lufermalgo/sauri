"""Migration 028_auth_refresh_tokens: single head, upgrade and downgrade on disposable PostgreSQL (#1123)."""

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
REVISION = "028_auth_refresh_tokens"
PARENT = "027_engine_fallback_reason"

INSERT_TOKEN = (
    "INSERT INTO auth_refresh_tokens (id, user_id, family_id, token_hash, token_version, issued_at, "
    "idle_expires_at, absolute_expires_at) VALUES ($1, 'u', 'f', $2, 0, now(), now(), now())"
)


def test_revision_is_the_single_head_and_follows_engine_fallback_reason() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["029_meeting_recorded_at"]  # The recording-date revision follows.
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32)


async def test_upgrade_and_downgrade_with_data_on_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    url = make_url(raw)
    assert "sauri_qa" in (url.database or ""), "QA database required"
    database = f"sauri_qa_refreshmig_{uuid.uuid4().hex}"
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
            "INSERT INTO users (id, email, name, password_hash, is_sales, created_at, token_version) "
            "VALUES ('u', 'u@example.test', 'S', 'pbkdf2_sha256$1$aa$bb', true, now(), 3)"
        )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        assert await connection.fetchval("SELECT count(*) FROM auth_refresh_tokens") == 0
        await connection.execute(INSERT_TOKEN, "t1", "a" * 64)
        with pytest.raises(asyncpg.UniqueViolationError):  # The digest identifies the token.
            await connection.execute(INSERT_TOKEN, "t2", "a" * 64)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute(INSERT_TOKEN.replace("'u'", "'nobody'", 1), "t3", "b" * 64)
        indexes = {row["indexname"] for row in await connection.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'auth_refresh_tokens'"
        )}
        assert {"ix_auth_refresh_tokens_family_id", "ix_auth_refresh_tokens_user_id"} <= indexes
        columns = {row["column_name"] for row in await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'auth_refresh_tokens'"
        )}
        assert columns == {
            "id", "user_id", "family_id", "token_hash", "token_version", "issued_at", "last_used_at",
            "idle_expires_at", "absolute_expires_at", "rotated_at", "revoked_at",
        }  # No address, agent or any other client detail.

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        assert await connection.fetchval("SELECT to_regclass('auth_refresh_tokens')") is None
        assert await connection.fetchval("SELECT token_version FROM users WHERE id = 'u'") == 3  # Nothing else touched.
        assert await connection.fetchval("SELECT count(*) FROM users") == 1

        await asyncio.to_thread(command.upgrade, config, REVISION)
        await connection.execute(INSERT_TOKEN, "t4", "c" * 64)
        await connection.execute("DELETE FROM users WHERE id = 'u'")  # Removing an account removes its tokens.
        assert await connection.fetchval("SELECT count(*) FROM auth_refresh_tokens") == 0
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
