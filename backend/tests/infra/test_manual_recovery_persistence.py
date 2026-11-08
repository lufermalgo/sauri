"""Durable schema contract for synthetic manual recovery records."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infra.database import Base
from app.infra import models as _models  # noqa: F401 -- register ORM tables

RECOVERY_TABLES = {
    "meeting_processing_claims",
    "meeting_recovery_operations",
    "meeting_recovery_outbox",
    "manual_recovery_pilot_gate",
}

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
