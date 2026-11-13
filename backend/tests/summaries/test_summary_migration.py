"""Isolated PostgreSQL 16 upgrade/downgrade contract for summary persistence (T2/#270)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]  # asyncpg does not ship py.typed; exercised against PG16.
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command

BACKEND = Path(__file__).resolve().parents[2]
PARENT = "013_manual_recovery_persistence"
SUMMARY = "014_meeting_summaries_templates"
# Capture columns, keys and indexes of 012/013 artifacts, not only their table names.
PRESERVED = (
    "diarizations", "speaker_assignments", "meeting_processing_claims",
    "meeting_recovery_operations", "meeting_recovery_outbox", "manual_recovery_pilot_gate",
)


async def _snapshot(
    connection: asyncpg.Connection,
) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str]]]:
    columns = await connection.fetch(
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = ANY($1::text[]) ORDER BY table_name, ordinal_position",
        list(PRESERVED),
    )
    constraints = await connection.fetch(
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE n.nspname = 'public' AND c.conrelid::regclass::text = ANY($1::text[]) "
        "ORDER BY 1, 2", list(PRESERVED),
    )
    indexes = await connection.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = ANY($1::text[]) ORDER BY 1, 2",
        list(PRESERVED),
    )
    return (
        [tuple(row) for row in columns],
        [tuple(row) for row in constraints] + [tuple(row) for row in indexes],
    )


@pytest.mark.asyncio
async def test_postgres_summary_upgrade_downgrade_preserves_published_012_013(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_url = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("requires isolated PostgreSQL 16 admin URL in SAURI_MIGRATION_TEST_ADMIN_URL")

    parsed = make_url(admin_url)
    db_name = f"sauri_summary_qa_{uuid4().hex}"
    args: dict[str, str | int] = {
        "user": parsed.username or "", "database": parsed.database or "postgres",
    }
    if parsed.password is not None:
        args["password"] = parsed.password
    if parsed.host is not None:
        args["host"] = parsed.host
    if parsed.port is not None:
        args["port"] = parsed.port
    admin = await asyncpg.connect(**args)
    try:
        server_version = int(await admin.fetchval("SHOW server_version_num"))
        assert 160000 <= server_version < 170000, f"PostgreSQL 16 required, found {server_version}"
        await admin.execute(f'CREATE DATABASE "{db_name}"')
        monkeypatch.setenv("DATABASE_URL", parsed.set(database=db_name).render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, PARENT)
        connection = await asyncpg.connect(**(args | {"database": db_name}))
        try:
            meeting_id, transcript_id, user_id, diarization_id = (str(uuid4()) for _ in range(4))
            await connection.execute(
                "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
                "VALUES ($1, $2, 'Synthetic', 'test-hash', true, now())",
                user_id, f"{user_id}@example.test",
            )
            await connection.execute(
                "INSERT INTO meetings (id, meet_link, origin, process_state, created_by, created_at) "
                "VALUES ($1, 'https://meet.google.com/abc-defg-hij', 'link', 'completed', $2, now())",
                meeting_id, user_id,
            )
            await connection.execute(
                "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
                "VALUES ($1, $2, 'es-CO', 'synthetic', true, now())",
                transcript_id, meeting_id,
            )
            await connection.execute(
                "INSERT INTO diarizations "
                "(id, meeting_id, transcript_id, provider, speaker_count, processing_revision, is_legacy, "
                "diarization_state, created_at, updated_at) "
                "VALUES ($1, $2, $3, 'synthetic', 0, 3, false, 'completed', now(), now())",
                diarization_id, meeting_id, transcript_id,
            )
            await connection.execute(
                "INSERT INTO meeting_processing_claims (meeting_id, generation) VALUES ($1, 7)", meeting_id,
            )
            before = await _snapshot(connection)
            assert len({row[0] for row in before[0]}) == len(PRESERVED)
            await asyncio.to_thread(command.upgrade, config, SUMMARY)
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == SUMMARY
            assert before == await _snapshot(connection)
            assert await connection.fetchval("SELECT count(*) FROM summary_templates") == 0
            assert await connection.fetchval(
                "SELECT default_summary_template_id FROM users WHERE id=$1", user_id
            ) is None
            fk = await connection.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='fk_users_default_summary_template_id_summary_templates'"
            )
            assert fk is not None and "ON DELETE SET NULL" in fk
            summary_constraints = {
                row["conname"]: row["definition"]
                for row in await connection.fetch(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conrelid='meeting_summaries'::regclass"
                )
            }
            assert "ON DELETE CASCADE" in next(
                definition for definition in summary_constraints.values()
                if "FOREIGN KEY (transcript_id)" in definition
            )
            assert "ON DELETE CASCADE" in next(
                definition for definition in summary_constraints.values()
                if "FOREIGN KEY (meeting_id)" in definition
            )
            assert "uq_meeting_summary_event_id" in summary_constraints
            assert "uq_meeting_summary_transcript_generation" in summary_constraints
            category_id, template_id, event_id, summary_id = (str(uuid4()) for _ in range(4))
            await connection.execute(
                "INSERT INTO template_categories (id, owner_user_id, name, created_at) "
                "VALUES ($1, $2, 'Synthetic', now())", category_id, user_id,
            )
            await connection.execute(
                "INSERT INTO summary_templates "
                "(id, owner_user_id, category_id, name, version, instructions, created_at, updated_at) "
                "VALUES ($1, $2, $3, 'Synthetic', 1, 'synthetic', now(), now())",
                template_id, user_id, category_id,
            )
            await connection.execute(
                "UPDATE users SET default_summary_template_id=$1 WHERE id=$2", template_id, user_id,
            )
            await connection.execute(
                "INSERT INTO summary_request_outbox "
                "(event_id, meeting_id, transcript_id, template_id, template_version, "
                "instructions_snapshot, generation, status) VALUES ($1,$2,$3,$4,1,'synthetic',1,'succeeded')",
                event_id, meeting_id, transcript_id, template_id,
            )
            await connection.execute(
                "INSERT INTO processed_summary_events (event_id, meeting_id, completed_at) "
                "VALUES ($1,$2,now())", event_id, meeting_id,
            )
            await connection.execute(
                "INSERT INTO meeting_summaries "
                "(id,event_id,meeting_id,transcript_id,template_id,template_version,topic,key_points_json,"
                "generation,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,1,'Topic','[\"Point\"]',1,now(),now())",
                summary_id, event_id, meeting_id, transcript_id, template_id,
            )
            assert await connection.fetchval("SELECT count(*) FROM meeting_summaries") == 1
            await asyncio.to_thread(command.downgrade, config, PARENT)
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == PARENT
            assert before == await _snapshot(connection)
            for table in ("template_categories", "summary_templates", "summary_request_outbox",
                          "processed_summary_events", "meeting_summaries"):
                assert await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
            assert await connection.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='default_summary_template_id'"
            ) == 0
            assert await connection.fetchval(
                "SELECT processing_revision FROM diarizations WHERE id=$1", diarization_id
            ) == 3
            assert await connection.fetchval(
                "SELECT generation FROM meeting_processing_claims WHERE meeting_id=$1", meeting_id
            ) == 7
        finally:
            await connection.close()
    finally:
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", db_name)
        await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        await admin.close()
