"""Durable schema contract for synthetic manual recovery records."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infra.database import Base
from app.infra import models as _models  # noqa: F401 -- register ORM tables
from tests.test_migration import (
    _load_published_migration,
    _migration_script,
    _run_migration,
)

RECOVERY_TABLES = {
    "meeting_processing_claims",
    "meeting_recovery_operations",
    "meeting_recovery_outbox",
    "manual_recovery_pilot_gate",
}

RECOVERY_MIGRATION_FILENAME = "013_manual_recovery_persistence.py"
RECOVERY_MIGRATION_REVISION = "013_manual_recovery_persistence"
RECOVERY_MIGRATION_PARENT = "012_diarization_generations"

FORBIDDEN_CONTENT_FIELDS = {
    "transcript",
    "transcript_text",
    "notes",
    "raw_payload",
    "broker_payload",
    "audio_ref",
    "video_ref",
    "media_ref",
    "object_ref",
}


def _schema_contract(connection: Connection) -> dict[str, object]:
    inspector = sa_inspect(connection)
    tables = set(inspector.get_table_names())
    recovery_tables = RECOVERY_TABLES & tables

    columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in recovery_tables
    }
    unique_constraints = {
        table_name: {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        }
        for table_name in recovery_tables
    }
    foreign_keys = {
        table_name: {
            (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        for table_name in recovery_tables
    }
    primary_keys = {
        table_name: set(inspector.get_pk_constraint(table_name)["constrained_columns"])
        for table_name in recovery_tables
    }
    return {
        "tables": tables,
        "columns": columns,
        "unique_constraints": unique_constraints,
        "foreign_keys": foreign_keys,
        "primary_keys": primary_keys,
    }


@pytest.mark.asyncio
async def test_recovery_schema_is_durable_scoped_and_content_free(
    async_engine: AsyncEngine,
) -> None:
    async with async_engine.connect() as connection:
        schema = await connection.run_sync(_schema_contract)

    tables = schema["tables"]
    assert isinstance(tables, set)
    assert RECOVERY_TABLES <= tables, (
        "missing durable recovery schema tables: " f"{sorted(RECOVERY_TABLES - tables)}"
    )

    columns = schema["columns"]
    assert isinstance(columns, dict)
    assert columns["meeting_processing_claims"] >= {
        "meeting_id",
        "generation",
        "claim_id",
    }
    assert columns["meeting_recovery_operations"] >= {
        "id",
        "meeting_id",
        "actor_id",
        "idempotency_key",
        "processing_generation",
        "created_at",
    }
    assert columns["meeting_recovery_outbox"] >= {
        "id",
        "operation_id",
        "topic",
        "job_identifiers",
        "delivery_status",
    }
    assert columns["manual_recovery_pilot_gate"] >= {"id", "status"}

    for table_name, table_columns in columns.items():
        assert not (table_columns & FORBIDDEN_CONTENT_FIELDS), (
            f"{table_name} must not persist transcript, notes, raw broker payload, "
            "or media-reference fields"
        )

    unique_constraints = schema["unique_constraints"]
    assert isinstance(unique_constraints, dict)
    assert ("actor_id", "meeting_id", "idempotency_key") in unique_constraints[
        "meeting_recovery_operations"
    ]
    assert ("operation_id",) in unique_constraints["meeting_recovery_outbox"]
    assert ("meeting_id",) in unique_constraints["meeting_processing_claims"]

    foreign_keys = schema["foreign_keys"]
    assert isinstance(foreign_keys, dict)
    assert (("meeting_id",), "meetings") in foreign_keys[
        "meeting_recovery_operations"
    ]
    assert (("actor_id",), "users") in foreign_keys["meeting_recovery_operations"]
    assert (("operation_id",), "meeting_recovery_operations") in foreign_keys[
        "meeting_recovery_outbox"
    ]
    assert (("meeting_id",), "meetings") in foreign_keys[
        "meeting_processing_claims"
    ]

    primary_keys = schema["primary_keys"]
    assert isinstance(primary_keys, dict)
    assert primary_keys["manual_recovery_pilot_gate"] == {"id"}

    # Creating the recovery schema must retain pre-existing meeting/artifact tables.
    assert {
        "meetings",
        "session_recordings",
        "transcripts",
        "diarizations",
        "speaker_reviews",
    } <= tables
    assert "state_history" in tables


@pytest.mark.asyncio
async def test_recovery_schema_is_registered_in_orm_metadata(
    async_engine: AsyncEngine,
) -> None:
    del async_engine  # the fixture creates all registered ORM tables

    assert RECOVERY_TABLES <= set(Base.metadata.tables)


def _recovery_migration():
    script = _migration_script()
    heads = script.get_heads()
    assert RECOVERY_MIGRATION_REVISION in heads, (
        "missing sequential recovery persistence migration; "
        f"expected {RECOVERY_MIGRATION_REVISION!r} as a head, found {heads!r}"
    )

    migration = _load_published_migration(RECOVERY_MIGRATION_FILENAME)
    assert migration.revision == RECOVERY_MIGRATION_REVISION
    assert migration.down_revision == RECOVERY_MIGRATION_PARENT
    return migration


async def _seed_existing_meeting_artifacts(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        # The fixture's ORM create_all may already register the future recovery
        # models after T-2. Remove only those new tables before applying the
        # migration under test; preserve all pre-existing meeting data.
        for table_name in (
            "meeting_recovery_outbox",
            "meeting_recovery_operations",
            "meeting_processing_claims",
            "manual_recovery_pilot_gate",
        ):
            await connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

        await connection.execute(
            text(
                "INSERT INTO meetings "
                "(id, origin, process_state, created_by, created_at) "
                "VALUES ('synthetic-meeting', 'link', 'completed', "
                "'synthetic-user', '2026-01-01 00:00:00')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO state_history "
                "(id, meeting_id, state, failure_cause, occurred_at) "
                "VALUES ('synthetic-history', 'synthetic-meeting', 'completed', "
                "NULL, '2026-01-01 00:00:01')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO session_recordings "
                "(id, meeting_id, idempotency_key, capture_origin, audio_ref, "
                "video_ref, duration_seconds, interrupted, expires_at, finished_at, "
                "video_presence) VALUES ('synthetic-recording', 'synthetic-meeting', "
                "'synthetic-key', 'web_upload', 'synthetic/audio.webm', NULL, 60, "
                "0, NULL, '2026-01-01 00:01:00', 'unknown')"
            )
        )


@pytest.mark.asyncio
async def test_recovery_migration_rollback_preserves_existing_meeting_artifacts(
    async_engine: AsyncEngine,
) -> None:
    migration = _recovery_migration()
    await _seed_existing_meeting_artifacts(async_engine)

    await _run_migration(async_engine, migration, "upgrade")
    await _run_migration(async_engine, migration, "downgrade")

    async with async_engine.connect() as connection:
        meeting = (
            await connection.execute(
                text(
                    "SELECT id, process_state, created_by FROM meetings "
                    "WHERE id = 'synthetic-meeting'"
                )
            )
        ).all()
        history = (
            await connection.execute(
                text(
                    "SELECT id, meeting_id, state, failure_cause FROM state_history "
                    "WHERE id = 'synthetic-history'"
                )
            )
        ).all()
        recordings = (
            await connection.execute(
                text(
                    "SELECT id, meeting_id, audio_ref, video_ref "
                    "FROM session_recordings WHERE id = 'synthetic-recording'"
                )
            )
        ).all()

    assert meeting == [("synthetic-meeting", "completed", "synthetic-user")]
    assert history == [
        ("synthetic-history", "synthetic-meeting", "completed", None)
    ]
    assert recordings == [
        (
            "synthetic-recording",
            "synthetic-meeting",
            "synthetic/audio.webm",
            None,
        )
    ]
