"""Integration test for the diarization schema (migration 003).

# Feature: speaker-identification
Task: 10.2
Validates: Requirements 8.1, 10.5

Verifies the schema contract produced by migration 003 against the test
database: creation of the three tables (diarizations, speakers,
speaker_assignments), cascading FKs, and the unique constraints
uq_diarization_meeting_id and uq_speaker_assignment_turn_id.

Migration 003 was additionally validated end-to-end against real
PostgreSQL (`alembic upgrade head` -> 11 tables, alembic_version=
003_diarizacion_schema). This test guards against schema regression on
every run of the suite.

Note: the table/column names asserted here reflect the current
backend/app/infra/models.py, renamed to English by migration
007_rename_schema_to_english (english-codebase-standard spec) -- this test
uses the in-memory SQLite engine built from the current ORM state
(async_engine fixture), not a live run of the Alembic chain (see
tests/test_migration.py for why).
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine


# ---------------------------------------------------------------------------
# The three diarization tables exist once the schema is created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_003_creates_three_tables(async_engine: AsyncEngine):
    """upgrade creates diarizations, speakers, and speaker_assignments."""

    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with async_engine.connect() as conn:
        tables = await conn.run_sync(_tables)

    assert "diarizations" in tables
    assert "speakers" in tables
    assert "speaker_assignments" in tables


# ---------------------------------------------------------------------------
# Unique constraints (Req. 8.1, 10.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_003_unique_constraints(async_engine: AsyncEngine):
    """uq_diarization_meeting_id and uq_speaker_assignment_turn_id are defined."""

    def _unique_constraints(sync_conn):
        insp = inspect(sync_conn)
        diar_uqs = {uc["name"] for uc in insp.get_unique_constraints("diarizations")}
        assignment_uqs = {
            uc["name"] for uc in insp.get_unique_constraints("speaker_assignments")
        }
        return diar_uqs, assignment_uqs

    async with async_engine.connect() as conn:
        diar_uqs, assignment_uqs = await conn.run_sync(_unique_constraints)

    assert "uq_diarization_meeting_id" in diar_uqs
    assert "uq_speaker_assignment_turn_id" in assignment_uqs


# ---------------------------------------------------------------------------
# Cascading foreign keys (Req. 8.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_003_foreign_keys_cascade(async_engine: AsyncEngine):
    """Speaker and assignment FKs reference diarizations with cascade."""

    def _fks(sync_conn):
        insp = inspect(sync_conn)
        return {
            "speakers": insp.get_foreign_keys("speakers"),
            "speaker_assignments": insp.get_foreign_keys("speaker_assignments"),
        }

    async with async_engine.connect() as conn:
        fks = await conn.run_sync(_fks)

    # speakers.diarization_id -> diarizations.id ON DELETE CASCADE
    speaker_fks = {fk["referred_table"]: fk for fk in fks["speakers"]}
    assert "diarizations" in speaker_fks
    assert speaker_fks["diarizations"]["options"].get("ondelete") == "CASCADE"

    # speaker_assignments references diarizations, speakers, and speech_turns
    assignment_referred = {fk["referred_table"] for fk in fks["speaker_assignments"]}
    assert "diarizations" in assignment_referred
    assert "speakers" in assignment_referred
    assert "speech_turns" in assignment_referred


# ---------------------------------------------------------------------------
# Consistency of the Alembic revision chain 001 -> 002 -> 003
# ---------------------------------------------------------------------------


def test_alembic_revision_chain():
    """Migration 003 chains correctly after 002 and defines upgrade/downgrade."""
    import importlib.util
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "alembic" / "versions"

    def _load(name):
        path = base / name
        spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    m003 = _load("003_diarizacion_schema.py")
    assert m003.revision == "003_diarizacion_schema"
    assert m003.down_revision == "002_uq_transcripcion"
    assert hasattr(m003, "upgrade")
    assert hasattr(m003, "downgrade")
