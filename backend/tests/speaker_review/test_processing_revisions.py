"""RED contracts for exact processing-revision isolation and admission.

Feature: recording-speaker-review, T-8 RED
Validates: approved tasks.md T-8 and design.md revision-state boundary.
All identifiers and rows in this module are synthetic. No production code is
changed by this task.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "alembic" / "versions"
LEGACY_REVISION = 1


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_migration():
    """Find the migration that introduces exact processing revisions."""
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = _load_migration(path)
        source = inspect.getsource(module)
        if "processing_revision_id" in source or "processing_state" in source:
            return module
    pytest.fail("no migration introduces processing revisions and processing state")


async def _run_migration(engine: AsyncEngine, migration, direction: str) -> None:
    async with engine.begin() as connection:
        def run(sync_connection) -> None:
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                getattr(migration, direction)()

        await connection.run_sync(run)


async def _seed_legacy_stage_rows(engine: AsyncEngine) -> None:
    """Create complete and partial legacy records without customer data."""
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS diarizations"))
        await connection.execute(text("DROP TABLE IF EXISTS transcripts"))
        await connection.execute(
            text(
                "CREATE TABLE transcripts (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) NOT NULL, "
                "content TEXT NOT NULL, UNIQUE(meeting_id))"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE diarizations (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) NOT NULL, "
                "content TEXT NOT NULL, UNIQUE(meeting_id))"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO transcripts (id, meeting_id, content) VALUES "
                "('transcript-complete', 'meeting-complete', 'synthetic transcript'), "
                "('transcript-partial', 'meeting-partial', 'synthetic partial transcript')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO diarizations (id, meeting_id, content) VALUES "
                "('diarization-complete', 'meeting-complete', 'synthetic diarization')"
            )
        )


@pytest.mark.asyncio
async def test_revision_migration_backfills_complete_and_partial_legacy_rows(
    async_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    assert migration.down_revision in {
        "009_recording_media_sources",
        "009_speaker_review_idempotency_receipts",
    }
    await _seed_legacy_stage_rows(async_engine)

    await _run_migration(async_engine, migration, "upgrade")

    async with async_engine.connect() as connection:
        transcript_revisions = (
            await connection.execute(
                text("SELECT meeting_id, processing_revision_id FROM transcripts ORDER BY meeting_id")
            )
        ).all()
        diarization_revisions = (
            await connection.execute(
                text("SELECT meeting_id, processing_revision_id FROM diarizations ORDER BY meeting_id")
            )
        ).all()
    assert transcript_revisions == [
        ("meeting-complete", LEGACY_REVISION),
        ("meeting-partial", LEGACY_REVISION),
    ]
    assert diarization_revisions == [("meeting-complete", LEGACY_REVISION)]


@pytest.mark.asyncio
async def test_revision_migration_replaces_meeting_only_uniqueness(
    async_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    await _seed_legacy_stage_rows(async_engine)
    await _run_migration(async_engine, migration, "upgrade")

    async with async_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO transcripts (id, meeting_id, content, processing_revision_id) "
                "VALUES ('transcript-revision-2', 'meeting-complete', 'new synthetic transcript', 2)"
            )
        )
        with pytest.raises(Exception):
            await connection.execute(
                text(
                    "INSERT INTO transcripts (id, meeting_id, content, processing_revision_id) "
                    "VALUES ('transcript-duplicate-revision', 'meeting-complete', 'duplicate', 2)"
                )
            )


@pytest.mark.asyncio
async def test_processing_state_schema_has_distinct_active_and_in_flight_pointers(
    async_engine: AsyncEngine,
) -> None:
    def inspect_schema(sync_connection):
        inspector = sa_inspect(sync_connection)
        names = set(inspector.get_table_names())
        state_table = next(
            (name for name in names if name in {"recording_processing_states", "processing_states"}),
            None,
        )
        assert state_table is not None, "per-recording processing state table is required"
        return {column["name"] for column in inspector.get_columns(state_table)}

    async with async_engine.connect() as connection:
        columns = await connection.run_sync(inspect_schema)
    assert "active_processing_revision_id" in columns
    assert "in_flight_revision_id" in columns


def test_revision_qualified_review_routes_are_registered() -> None:
    """The revision path is explicit for writes and excerpt reads."""
    from app.main import app

    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
    assert "/api/v1/meetings/{meeting_id}/speaker-review" in routes
    assert (
        "/api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}"
        in routes
    )
    assert (
        "/api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}/excerpt"
        in routes
    )
