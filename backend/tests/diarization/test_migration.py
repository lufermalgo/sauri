"""Integration test for the diarization schema (migration 003).

# Feature: speaker-identification
Task: 10.2
Validates: Requirements 8.1, 10.5

Verifies migration 003's historical tables and FKs, and T5's generation
migration from synthetic revision-011 data. Revision 003's original unique
constraints are replaced by revision 012's generation-scoped constraints.

Migration 003 was additionally validated end-to-end against real
PostgreSQL (`alembic upgrade head` -> 11 tables, alembic_version=
003_diarizacion_schema). This test guards against schema regression on
every run of the suite.

Note: the table/column names asserted here reflect the current
backend/app/infra/models.py, renamed to English by migration
007_rename_schema_to_english -- this test
uses the in-memory SQLite engine built from the current ORM state
(async_engine fixture), not a live run of the Alembic chain (see
tests/test_migration.py for why).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

# ---------------------------------------------------------------------------
# The three diarization tables exist once the schema is created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_003_creates_three_tables(async_engine: AsyncEngine) -> None:
    """upgrade creates diarizations, speakers, and speaker_assignments."""

    def _tables(sync_conn: Connection) -> set[str]:
        return set(inspect(sync_conn).get_table_names())

    async with async_engine.connect() as conn:
        tables = await conn.run_sync(_tables)

    assert "diarizations" in tables
    assert "speakers" in tables
    assert "speaker_assignments" in tables


# ---------------------------------------------------------------------------
# Unique constraints (Req. 8.1, 10.5)
# ---------------------------------------------------------------------------


def test_migration_003_historical_unique_constraints() -> None:
    """Revision 003 established the old uniques; T6 replaces them in current ORM."""
    base = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    original = (base / "003_diarizacion_schema.py").read_text(encoding="utf-8")
    rename = (base / "007_rename_schema_to_english.py").read_text(encoding="utf-8")
    assert 'name="uq_diarizacion_reunion_id"' in original
    assert 'name="uq_asignacion_turno_id"' in original
    assert "uq_diarizacion_reunion_id TO uq_diarization_meeting_id" in rename
    assert "uq_asignacion_turno_id TO uq_speaker_assignment_turn_id" in rename


@pytest.mark.asyncio
async def test_migration_003_unique_constraints(async_engine: AsyncEngine) -> None:
    """The current ORM schema defines generation-scoped unique constraints."""

    def _unique_constraints(
        sync_conn: Connection,
    ) -> tuple[set[str | None], dict[str | None, tuple[str, ...]]]:
        insp = inspect(sync_conn)
        diar_uqs = {uc["name"] for uc in insp.get_unique_constraints("diarizations")}
        assignment_uqs = {
            uc["name"]: tuple(uc["column_names"])
            for uc in insp.get_unique_constraints("speaker_assignments")
        }
        return diar_uqs, assignment_uqs

    async with async_engine.connect() as conn:
        diar_uqs, assignment_uqs = await conn.run_sync(_unique_constraints)

    assert "uq_diarization_meeting_revision" in diar_uqs
    assert assignment_uqs["uq_speaker_assignment_diarization_turn"] == (
        "diarization_id",
        "turn_id",
    )


# ---------------------------------------------------------------------------
# Cascading foreign keys (Req. 8.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_003_foreign_keys_cascade(async_engine: AsyncEngine) -> None:
    """Speaker and assignment FKs reference diarizations with cascade."""

    def _fks(sync_conn: Connection) -> dict[str, Sequence[Any]]:
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


def test_alembic_revision_chain() -> None:
    """Migration 003 chains correctly after 002 and defines upgrade/downgrade."""
    base = Path(__file__).resolve().parents[2] / "alembic" / "versions"

    def _load(name: str) -> ModuleType:
        path = base / name
        spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    m003 = _load("003_diarizacion_schema.py")
    assert m003.revision == "003_diarizacion_schema"
    assert m003.down_revision == "002_uq_transcripcion"
    assert hasattr(m003, "upgrade")
    assert hasattr(m003, "downgrade")


# ---------------------------------------------------------------------------
# T5: legacy data survives the generation migration, with synthetic IDs only
# ---------------------------------------------------------------------------


def _generation_migration() -> ModuleType:
    """Load the revision immediately following 011 without prescribing its filename."""
    base = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revisions = sorted(base.glob("012_*.py"))
    assert len(revisions) == 1, "Expected one generation migration after revision 011"
    spec = importlib.util.spec_from_file_location(revisions[0].stem, revisions[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "011_linkless_cleanup"
    return module


@pytest.mark.asyncio
async def test_generation_migration_preserves_legacy_rows_and_review(
    async_engine: AsyncEngine,
) -> None:
    """Upgrade seeded revision-011 rows without rewriting source or review IDs."""
    from app.infra.database import Base

    ids = {
        key: str(uuid4())
        for key in (
            "meeting",
            "transcript",
            "turn",
            "diarization",
            "speaker",
            "assignment",
            "review",
            "item",
            "receipt",
        )
    }
    now = datetime.now(UTC)
    async with async_engine.begin() as conn:
        # Reconstruct the revision-011 tables involved in generation lineage,
        # independently of the future ORM. Enforce the real FK relationships.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
        for ddl in (
            "CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE transcripts (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) "
            "NOT NULL REFERENCES meetings(id) ON DELETE CASCADE)",
            "CREATE TABLE speech_turns (id VARCHAR(36) PRIMARY KEY, transcript_id VARCHAR(36) "
            "NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE, text TEXT, "
            "start_ms INTEGER, end_ms INTEGER, sequence INTEGER)",
            "CREATE TABLE diarizations (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) "
            "NOT NULL REFERENCES meetings(id), transcript_id VARCHAR(36) NOT NULL "
            "REFERENCES transcripts(id), provider VARCHAR(128) NOT NULL, speaker_count INTEGER, "
            "diarization_state VARCHAR(32), failure_cause VARCHAR(64), created_at DATETIME, "
            "updated_at DATETIME, CONSTRAINT uq_diarization_meeting_id UNIQUE(meeting_id))",
            "CREATE TABLE speakers (id VARCHAR(36) PRIMARY KEY, diarization_id VARCHAR(36) "
            "NOT NULL REFERENCES diarizations(id) ON DELETE CASCADE, raw_label VARCHAR(128), "
            "label VARCHAR(64), sequence INTEGER)",
            "CREATE TABLE speaker_assignments (id VARCHAR(36) PRIMARY KEY, "
            "diarization_id VARCHAR(36) NOT NULL REFERENCES diarizations(id) ON DELETE CASCADE, "
            "turn_id VARCHAR(36) NOT NULL REFERENCES speech_turns(id), speaker_id VARCHAR(36) "
            "NOT NULL REFERENCES speakers(id) ON DELETE CASCADE, "
            "CONSTRAINT uq_speaker_assignment_turn_id UNIQUE(turn_id))",
            "CREATE TABLE speaker_reviews (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) "
            "NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, processing_revision INTEGER NOT NULL, "
            "status VARCHAR(16), created_at DATETIME, "
            "CONSTRAINT uq_speaker_review_revision UNIQUE(meeting_id, processing_revision))",
            "CREATE TABLE speaker_review_items (id VARCHAR(36) PRIMARY KEY, review_id VARCHAR(36) "
            "NOT NULL REFERENCES speaker_reviews(id) ON DELETE CASCADE, speaker_key VARCHAR(128) NOT NULL, "
            "current_label VARCHAR(64) NOT NULL, excerpt_ref VARCHAR(2048), disposition VARCHAR(16), "
            "chosen_label VARCHAR(64), attribution_state VARCHAR(16) NOT NULL, version INTEGER NOT NULL, "
            "CONSTRAINT uq_speaker_review_item_speaker UNIQUE(review_id, speaker_key))",
            "CREATE TABLE speaker_review_idempotency_receipts (id VARCHAR(36) PRIMARY KEY, "
            "review_id VARCHAR(36) NOT NULL REFERENCES speaker_reviews(id) ON DELETE CASCADE, "
            "item_id VARCHAR(36) NOT NULL REFERENCES speaker_review_items(id) ON DELETE CASCADE, "
            "idempotency_key VARCHAR(256) NOT NULL, request_hash VARCHAR(64) NOT NULL, response JSON NOT NULL, "
            "CONSTRAINT uq_review_idempotency_key UNIQUE(review_id, idempotency_key))",
        ):
            await conn.execute(text(ddl))
        for table, values in (
            ("meetings", {"id": ids["meeting"]}),
            ("transcripts", {"id": ids["transcript"], "meeting_id": ids["meeting"]}),
            (
                "speech_turns",
                {
                    "id": ids["turn"],
                    "transcript_id": ids["transcript"],
                    "text": "Synthetic source",
                    "start_ms": 100,
                    "end_ms": 900,
                    "sequence": 1,
                },
            ),
            (
                "diarizations",
                {
                    "id": ids["diarization"],
                    "meeting_id": ids["meeting"],
                    "transcript_id": ids["transcript"],
                    "provider": "synthetic",
                    "speaker_count": 1,
                    "diarization_state": "completed",
                    "created_at": now,
                    "updated_at": now,
                },
            ),
            (
                "speakers",
                {
                    "id": ids["speaker"],
                    "diarization_id": ids["diarization"],
                    "raw_label": "synthetic-0",
                    "label": "Speaker 1",
                    "sequence": 1,
                },
            ),
            (
                "speaker_assignments",
                {
                    "id": ids["assignment"],
                    "diarization_id": ids["diarization"],
                    "turn_id": ids["turn"],
                    "speaker_id": ids["speaker"],
                },
            ),
            (
                "speaker_reviews",
                {
                    "id": ids["review"],
                    "meeting_id": ids["meeting"],
                    "processing_revision": 1,
                    "status": "complete",
                    "created_at": now,
                },
            ),
            (
                "speaker_review_items",
                {
                    "id": ids["item"],
                    "review_id": ids["review"],
                    "speaker_key": ids["speaker"],
                    "current_label": "Speaker 1",
                    "excerpt_ref": "synthetic-encrypted-ref",
                    "disposition": "corrected",
                    "chosen_label": "Synthetic Name",
                    "attribution_state": "attributed",
                    "version": 2,
                },
            ),
            (
                "speaker_review_idempotency_receipts",
                {
                    "id": ids["receipt"],
                    "review_id": ids["review"],
                    "item_id": ids["item"],
                    "idempotency_key": "synthetic-key",
                    "request_hash": "a" * 64,
                    "response": '{"label":"Synthetic Name"}',
                },
            ),
        ):
            columns = ", ".join(values)
            params = ", ".join(f":{name}" for name in values)
            await conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)

        migration = _generation_migration()

        def _upgrade(sync_conn: Connection) -> None:
            context = MigrationContext.configure(sync_conn)
            with Operations.context(context):
                migration.upgrade()

        await conn.run_sync(_upgrade)
        legacy = (
            await conn.execute(
                text("SELECT id, processing_revision, is_legacy FROM diarizations WHERE id=:id"),
                {"id": ids["diarization"]},
            )
        ).one()
        assignment = (
            await conn.execute(
                text(
                    "SELECT id, diarization_id, turn_id, speaker_id, overlap_ms FROM speaker_assignments WHERE id=:id"
                ),
                {"id": ids["assignment"]},
            )
        ).one()
        speaker = (
            await conn.execute(
                text("SELECT id, diarization_id, raw_label, label, sequence FROM speakers WHERE id=:id"),
                {"id": ids["speaker"]},
            )
        ).one()
        review = (
            await conn.execute(
                text("SELECT id, meeting_id, processing_revision, status FROM speaker_reviews WHERE id=:id"),
                {"id": ids["review"]},
            )
        ).one()
        item = (
            await conn.execute(
                text(
                    "SELECT id, review_id, speaker_key, current_label, excerpt_ref, disposition, "
                    "chosen_label, attribution_state, version FROM speaker_review_items WHERE id=:id"
                ),
                {"id": ids["item"]},
            )
        ).one()
        receipt = (
            await conn.execute(
                text(
                    "SELECT id, review_id, item_id, idempotency_key, request_hash, response "
                    "FROM speaker_review_idempotency_receipts WHERE id=:id"
                ),
                {"id": ids["receipt"]},
            )
        ).one()
        source = (
            await conn.execute(
                text("SELECT text, start_ms, end_ms FROM speech_turns WHERE id=:id"), {"id": ids["turn"]}
            )
        ).one()
        assert legacy == (ids["diarization"], 1, True)
        assert assignment == (ids["assignment"], ids["diarization"], ids["turn"], ids["speaker"], None)
        assert speaker == (ids["speaker"], ids["diarization"], "synthetic-0", "Speaker 1", 1)
        assert review == (ids["review"], ids["meeting"], 1, "complete")
        assert item == (
            ids["item"],
            ids["review"],
            ids["speaker"],
            "Speaker 1",
            "synthetic-encrypted-ref",
            "corrected",
            "Synthetic Name",
            "attributed",
            2,
        )
        assert receipt == (
            ids["receipt"],
            ids["review"],
            ids["item"],
            "synthetic-key",
            "a" * 64,
            '{"label":"Synthetic Name"}',
        )
        assert source == ("Synthetic source", 100, 900)

        # A new generation can point to the same immutable source turn, but
        # cannot add the same source turn twice within its own generation.
        next_id, next_speaker, next_assignment = (str(uuid4()) for _ in range(3))
        await conn.execute(
            text(
                "INSERT INTO diarizations (id, meeting_id, transcript_id, provider, "
                "speaker_count, diarization_state, created_at, updated_at, "
                "processing_revision, is_legacy) VALUES "
                "(:id, :meeting, :transcript, 'synthetic', 1, 'completed', "
                ":now, :now, 2, false)"
            ),
            {"id": next_id, "meeting": ids["meeting"], "transcript": ids["transcript"], "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO speakers (id, diarization_id, raw_label, label, sequence) "
                "VALUES (:id, :diarization, 'synthetic-1', 'Speaker 1', 1)"
            ),
            {"id": next_speaker, "diarization": next_id},
        )
        await conn.execute(
            text(
                "INSERT INTO speaker_assignments "
                "(id, diarization_id, turn_id, speaker_id, overlap_ms) "
                "VALUES (:id, :diarization, :turn, :speaker, 800)"
            ),
            {"id": next_assignment, "diarization": next_id, "turn": ids["turn"], "speaker": next_speaker},
        )
        assert (
            await conn.execute(
                text("SELECT COUNT(*) FROM speaker_assignments WHERE turn_id=:turn"), {"turn": ids["turn"]}
            )
        ).scalar_one() == 2
        savepoint = await conn.begin_nested()
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO speaker_assignments "
                    "(id, diarization_id, turn_id, speaker_id, overlap_ms) "
                    "VALUES (:id, :diarization, :turn, :speaker, 800)"
                ),
                {"id": str(uuid4()), "diarization": next_id, "turn": ids["turn"], "speaker": next_speaker},
            )
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_generation_constraints_scope_assignment_to_diarization(
    async_engine: AsyncEngine,
) -> None:
    """Only the pair (diarization_id, turn_id) is unique across generations."""

    def _schema(sync_conn: Connection) -> tuple[set[str], set[str]]:
        insp = inspect(sync_conn)
        diar = {tuple(uc["column_names"]) for uc in insp.get_unique_constraints("diarizations")}
        assignments = {tuple(uc["column_names"]) for uc in insp.get_unique_constraints("speaker_assignments")}
        columns = {col["name"] for col in insp.get_columns("diarizations")}
        assignment_columns = {col["name"] for col in insp.get_columns("speaker_assignments")}
        assert {"processing_revision", "is_legacy"} <= columns
        assert "overlap_ms" in assignment_columns
        assert ("meeting_id", "processing_revision") in diar
        assert ("meeting_id",) not in diar
        assert ("diarization_id", "turn_id") in assignments
        assert ("turn_id",) not in assignments
        return columns, assignment_columns

    async with async_engine.connect() as conn:
        await conn.run_sync(_schema)
