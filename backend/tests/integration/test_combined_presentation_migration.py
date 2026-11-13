"""Combined #899/#900 migration preserves populated 014 data on PostgreSQL 16."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command


async def test_014_to_015_preserves_existing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("Requires exclusively disposable PostgreSQL admin URL")
    url = make_url(raw)
    name = f"sauri_qa_combined_migration_{uuid4().hex}"
    args = {"user": url.username, "password": url.password, "host": url.host,
            "port": url.port, "database": url.database}
    admin = await asyncpg.connect(**args)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        monkeypatch.setenv("DATABASE_URL", url.set(database=name).render_as_string(hide_password=False))
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, "014_meeting_summaries_templates")
        conn = await asyncpg.connect(**(args | {"database": name}))
        try:
            await conn.execute("INSERT INTO users (id,email,name,password_hash,is_sales) "
                               "VALUES ('u','synthetic@example.test','Synthetic','unused',true)")
            await conn.execute("INSERT INTO meetings (id,origin,process_state,created_by) "
                               "VALUES ('m','link','completed','u')")
            await conn.execute("INSERT INTO transcripts (id,meeting_id,language,provider,supports_turns) "
                               "VALUES ('t','m','es','synthetic',true)")
            await conn.execute("INSERT INTO speech_turns (id,transcript_id,text,start_ms,end_ms,sequence) "
                               "VALUES ('turn','t','Synthetic source',0,10000,1)")
            await conn.execute("INSERT INTO diarizations (id,meeting_id,transcript_id,diarization_state) "
                               "VALUES ('d','m','t','completed')")
            await conn.execute("INSERT INTO summary_templates "
                               "(id,owner_user_id,name,instructions,version,created_at,updated_at) "
                               "VALUES ('template','u','Synthetic','Synthetic instructions',1,now(),now())")
            tables = ("users", "meetings", "transcripts", "speech_turns", "diarizations", "summary_templates")
            before = {table: await conn.fetchval(f"SELECT jsonb_agg(to_jsonb(t)) FROM {table} t")
                      for table in tables}
            await asyncio.to_thread(command.upgrade, config, "head")
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == "015_final_presentation"
            for table in tables:
                expression = ("to_jsonb(t) - 'presentation' - 'prepared_result'"
                              if table == "diarizations" else "to_jsonb(t)")
                assert await conn.fetchval(f"SELECT jsonb_agg({expression}) FROM {table} t") == before[table]
            assert await conn.fetchval("SELECT presentation IS NULL AND prepared_result IS NULL FROM diarizations")
            await asyncio.to_thread(command.downgrade, config, "014_meeting_summaries_templates")
            for table in tables:
                assert await conn.fetchval(f"SELECT jsonb_agg(to_jsonb(t)) FROM {table} t") == before[table]
            await asyncio.to_thread(command.upgrade, config, "head")
        finally:
            await conn.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.close()
