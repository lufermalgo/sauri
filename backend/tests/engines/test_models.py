"""#1087 migration 026 on a disposable PostgreSQL: upgrade, constraints, downgrade, upgrade again."""

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
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.infra.database import Base

BACKEND = Path(__file__).parents[2]
REVISION = "026_engine_providers"
HEAD = "027_engine_fallback_reason"
PARENT = "025_auth_hardening"
NEW_TABLES = ("engine_providers", "engine_process_settings", "engine_privacy_consents")
PROVENANCE = ("engine_name", "engine_model", "engine_external")
PROVENANCE_TABLES = ("transcripts", "diarizations", "meeting_summaries")
# The only columns that mention keys: a reference and a display hint, never a value.
KEY_RELATED = {"secret_ref", "key_hint", "key_set_at"}
FORBIDDEN_WORDS = ("password", "token", "audio", "content", "text", "transcript_body", "secret_value", "api_key")


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


def test_revision_chain_ends_in_a_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT
    assert len(REVISION) <= 32  # alembic_version.version_num is VARCHAR(32)


async def test_models_declare_no_key_or_content_columns() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        names = await connection.run_sync(
            lambda sync: {
                table: {column["name"] for column in inspect(sync).get_columns(table)} for table in NEW_TABLES
            }
        )
        provenance = await connection.run_sync(
            lambda sync: {
                table: {column["name"]: column["nullable"] for column in inspect(sync).get_columns(table)}
                for table in PROVENANCE_TABLES
            }
        )
    await engine.dispose()
    for table, columns in names.items():
        assert not [c for c in columns if any(word in c for word in FORBIDDEN_WORDS)], table
        assert {c for c in columns if "key" in c or "secret" in c} <= KEY_RELATED, table
    for table, columns in provenance.items():
        assert all(name in columns and columns[name] for name in PROVENANCE), table  # present and nullable


async def test_upgrade_constraints_and_downgrade_on_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_QA_POSTGRES_URL") or os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_engines_mig_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, PARENT)
        connection = await asyncpg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False))
        for user in ("a", "b"):
            await connection.execute(
                "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
                f"VALUES ('{user}', '{user}@example.test', 'S', 'x', true, now())"
            )
        await connection.execute(
            "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
            "VALUES ('m', 'manual', 'completed', 'a', now())"
        )
        await connection.execute(
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('t', 'm', 'es', 'whisper.cpp', true, now())"
        )
        await connection.execute(
            "INSERT INTO diarizations "
            "(id, meeting_id, transcript_id, provider, diarization_state, created_at, updated_at) "
            "VALUES ('d', 'm', 't', 'senko', 'completed', now(), now())"
        )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
        for table in PROVENANCE_TABLES:  # old rows keep NULL provenance: "previous local engine"
            row = await connection.fetchrow(f"SELECT engine_name, engine_model, engine_external FROM {table} LIMIT 1")  # noqa: S608
            assert row is None or tuple(row) == (None, None, None)
        assert tuple(
            await connection.fetchrow("SELECT engine_name, engine_model, engine_external FROM transcripts")
        ) == (None, None, None)

        provider = (
            "INSERT INTO engine_providers (id, owner_id, kind, label, created_at, updated_at) "
            "VALUES ($1, $2, 'openai', $3, now(), now())"
        )
        await connection.execute(provider, "pa", "a", "A account")
        await connection.execute(provider, "pb", "b", "B account")
        assert await connection.fetchval("SELECT enabled FROM engine_providers WHERE id = 'pa'") is True
        with pytest.raises(asyncpg.UniqueViolationError):  # label is unique per owner
            await connection.execute(provider, "pa2", "a", "A account")
        await connection.execute(provider, "pa3", "b", "A account")  # another owner may reuse it

        setting = (
            "INSERT INTO engine_process_settings (owner_id, capability, provider_id, model, updated_at) "
            "VALUES ($1, $2, $3, $4, now())"
        )
        await connection.execute(setting, "a", "summary", "pa", "some-model")
        assert await connection.fetchval("SELECT local_fallback FROM engine_process_settings") is True
        assert await connection.fetchval("SELECT version FROM engine_process_settings") == 1
        with pytest.raises(asyncpg.UniqueViolationError):  # primary key (owner_id, capability)
            await connection.execute(setting, "a", "summary", "pa", "other")
        with pytest.raises(asyncpg.ForeignKeyViolationError):  # another owner's provider
            await connection.execute(setting, "a", "transcription", "pb", "m")
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(setting, "a", "audio", "pa", "m")
        with pytest.raises(asyncpg.CheckViolationError):  # a local choice must carry a local model
            await connection.execute(setting, "a", "diarization", None, "remote-model")
        await connection.execute(setting, "a", "diarization", None, "local:default")
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute("UPDATE engine_process_settings SET version = 0 WHERE capability = 'summary'")

        consent = (
            "INSERT INTO engine_privacy_consents "
            "(id, owner_id, capability, provider_id, notice_version, accepted_at, revoked_at) "
            "VALUES ($1, $2, $3, $4, $5, now(), $6)"
        )
        await connection.execute(consent, "c1", "a", "summary", "pa", 1, None)
        with pytest.raises(asyncpg.UniqueViolationError):  # one current consent per (owner, process, provider)
            await connection.execute(consent, "c2", "a", "summary", "pa", 1, None)
        await connection.execute("UPDATE engine_privacy_consents SET revoked_at = now() WHERE id = 'c1'")
        await connection.execute(consent, "c2", "a", "summary", "pa", 2, None)  # a new one after revoking
        await connection.execute(consent, "c3", "a", "transcription", "pa", 1, None)  # other process
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute(consent, "c4", "a", "summary", "pb", 1, None)  # another owner's provider
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(consent, "c5", "a", "summary", "pa", 0, None)

        await connection.execute("UPDATE engine_process_settings SET provider_id = NULL, model = 'local:default'")
        await connection.execute("DELETE FROM engine_providers WHERE id = 'pa'")
        assert await connection.fetchval("SELECT count(*) FROM engine_privacy_consents") == 0  # consents cascade

        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
        for table in NEW_TABLES:
            assert await connection.fetchval("SELECT to_regclass($1)", table) is None
        columns = await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ANY($1::text[])",
            list(PROVENANCE_TABLES),
        )
        assert not {row["column_name"] for row in columns} & set(PROVENANCE)
        assert await connection.fetchval("SELECT count(*) FROM meetings") == 1  # meeting data survives
        assert await connection.fetchval("SELECT count(*) FROM transcripts") == 1
        assert await connection.fetchval("SELECT count(*) FROM diarizations") == 1

        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert await connection.fetchval("SELECT count(*) FROM engine_providers") == 0
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
