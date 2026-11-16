"""Verify default-only DDL and optionally execute it in isolated QA PostgreSQL."""

from __future__ import annotations

import importlib.util
import io
import os
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "018_transcript_language_default"


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(REVISION, BACKEND / f"alembic/versions/{REVISION}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_language_migration_changes_only_the_default() -> None:
    module = migration()
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["025_auth_hardening"]
    assert script.get_revision("019_failed_summary_request").down_revision == REVISION
    assert module.down_revision == "017_transcript_words"
    for action, default in [("upgrade", "es"), ("downgrade", "es-CO")]:
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            getattr(module, action)()
        assert output.getvalue().strip() == f"ALTER TABLE transcripts ALTER COLUMN language SET DEFAULT '{default}';"


@pytest.mark.asyncio
async def test_language_default_on_real_postgres_preserves_existing_rows() -> None:
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("SAURI_QA_POSTGRES_URL not configured; offline PostgreSQL DDL test still runs")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql" and "sauri_qa" in (parsed.database or ""), "QA database required"
    engine = create_async_engine(parsed.set(drivername="postgresql+asyncpg"))
    schema = f"sauri_qa_language_{uuid.uuid4().hex}"
    module = migration()

    def apply(connection: Connection, action: str) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(module, action)()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.execute(text("CREATE TABLE transcripts (id int PRIMARY KEY, "
                                              "language varchar(16) NOT NULL DEFAULT 'es-CO')"))
                await connection.execute(text("INSERT INTO transcripts (id) VALUES (1)"))
                await connection.run_sync(apply, "upgrade")
                await connection.execute(text("INSERT INTO transcripts (id) VALUES (2)"))
                rows = (await connection.execute(text("SELECT language FROM transcripts ORDER BY id"))).scalars().all()
                assert rows == ["es-CO", "es"]
                await connection.run_sync(apply, "downgrade")
                await connection.execute(text("INSERT INTO transcripts (id) VALUES (3)"))
                rows = (await connection.execute(text("SELECT language FROM transcripts ORDER BY id"))).scalars().all()
                assert rows == ["es-CO", "es", "es-CO"]
            finally:
                await transaction.rollback()  # Includes the isolated schema, even on failure.
    finally:
        await engine.dispose()
