"""Tests for the schema rename migration.

Adaptation note: the project's existing migrations (001, 003, 005) use
Postgres-native `UUID` columns and raw `::uuid` casts, so the Alembic chain
cannot run against the SQLite in-memory engine this suite otherwise uses
(see conftest.py's `async_engine`), and running it against the live shared
dev Postgres container is out of scope for an automated test (it's a shared,
long-running instance other sessions may depend on). Data-preservation
(Propiedad 1 of design.md) is therefore validated two ways instead of a live
`alembic upgrade head` run:
  1. Statically: the migration's `upgrade()` source uses `op.rename_table` /
     `op.alter_column` for every renamed table, never `op.drop_table` /
     `op.create_table` — the operations Alembic runs are preserving by
     construction.
  2. Structurally: once `models.py` is updated (Tarea 2.6), the ORM schema
     built from `Base.metadata` (the same in-memory SQLite mechanism every
     other test in this suite uses) exposes the new English table/column
     names and no longer exposes the old Spanish ones.

These checks preserve migrated data and verify the current ORM schema without
running a destructive migration against the shared development database.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_FILENAME = "007_rename_schema_to_english.py"

OLD_TO_NEW_TABLES = {
    "reuniones": "meetings",
    "estado_historial": "state_history",
    "grabaciones_de_sesion": "session_recordings",
    "transcripciones": "transcripts",
    "turnos_de_habla": "speech_turns",
    "notificaciones_de_grabacion": "recording_notices",
    "registro_de_acceso": "access_log",
    "diarizaciones": "diarizations",
    "hablantes": "speakers",
    "asignaciones_de_hablante": "speaker_assignments",
    "usuarios": "users",
}


def _load_migration_module():
    path = MIGRATIONS_DIR / MIGRATION_FILENAME
    spec = importlib.util.spec_from_file_location(
        MIGRATION_FILENAME.replace(".py", ""), path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Revision chain (mirrors the existing test_cadena_de_revisiones_alembic
# pattern in backend/tests/diarizacion/test_migration.py)
# ---------------------------------------------------------------------------


def test_revision_007_chains_after_006() -> None:
    m007 = _load_migration_module()

    assert m007.revision == "007_rename_schema_to_english"
    assert m007.down_revision == "006_add_titulo_reunion"
    assert hasattr(m007, "upgrade")
    assert hasattr(m007, "downgrade")


# ---------------------------------------------------------------------------
# Propiedad 1 (static half): renames, not drop+recreate
# ---------------------------------------------------------------------------


def test_upgrade_renames_every_table_without_dropping_data() -> None:
    m007 = _load_migration_module()
    upgrade_source = inspect.getsource(m007.upgrade)

    assert "drop_table" not in upgrade_source
    assert "create_table" not in upgrade_source

    for old_name in OLD_TO_NEW_TABLES:
        assert f'"{old_name}"' in upgrade_source, (
            f"upgrade() must rename '{old_name}' via op.rename_table, "
            "not recreate it"
        )


def test_downgrade_reverses_every_rename() -> None:
    m007 = _load_migration_module()
    downgrade_source = inspect.getsource(m007.downgrade)

    assert "drop_table" not in downgrade_source
    assert "create_table" not in downgrade_source

    for new_name in OLD_TO_NEW_TABLES.values():
        assert f'"{new_name}"' in downgrade_source, (
            f"downgrade() must rename '{new_name}' back, not recreate it"
        )


# ---------------------------------------------------------------------------
# Propiedad 1 (structural half) + Propiedad 5: the ORM schema built from the
# current models.py exposes only the new English names.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orm_schema_uses_english_table_names(async_engine: AsyncEngine) -> None:
    def _table_names(sync_conn):
        return set(sa_inspect(sync_conn).get_table_names())

    async with async_engine.connect() as conn:
        tables = await conn.run_sync(_table_names)

    for old_name, new_name in OLD_TO_NEW_TABLES.items():
        assert new_name in tables, f"expected table '{new_name}' in models.py"
        assert old_name not in tables, f"table '{old_name}' should be gone from models.py"


@pytest.mark.asyncio
async def test_orm_schema_meetings_has_english_columns(async_engine: AsyncEngine) -> None:
    def _columns(sync_conn):
        return {c["name"] for c in sa_inspect(sync_conn).get_columns("meetings")}

    async with async_engine.connect() as conn:
        columns = await conn.run_sync(_columns)

    for expected in (
        "meet_link",
        "title",
        "origin",
        "calendar_invite_id",
        "scheduled_start_time",
        "process_state",
        "failure_cause",
        "created_by",
        "created_at",
    ):
        assert expected in columns, f"expected column 'meetings.{expected}'"

    for retired in ("enlace_meet", "estado_proceso", "creada_en", "creada_por", "titulo"):
        assert retired not in columns, f"column 'meetings.{retired}' should be renamed"


@pytest.mark.asyncio
async def test_orm_schema_users_has_english_columns(async_engine: AsyncEngine) -> None:
    def _columns(sync_conn):
        return {c["name"] for c in sa_inspect(sync_conn).get_columns("users")}

    async with async_engine.connect() as conn:
        columns = await conn.run_sync(_columns)

    assert "name" in columns
    assert "is_sales" in columns
    assert "created_at" in columns
    assert "nombre" not in columns
    assert "es_comercial" not in columns
    assert "creado_en" not in columns


# Playback source-inventory migration contract (T-1, issue #299)
PREVIOUS_REVISION = "008_speaker_review_aggregate"


def _source_inventory_migration():
    for path in MIGRATIONS_DIR.glob("*.py"):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if getattr(module, "down_revision", None) == PREVIOUS_REVISION:
            return module
    pytest.fail(f"no source-inventory migration follows {PREVIOUS_REVISION}")


async def _seed_legacy_recordings(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS recording_media_sources"))
        await connection.execute(text("DROP TABLE IF EXISTS session_recordings"))
        await connection.execute(
            text(
                "CREATE TABLE session_recordings ("
                "id VARCHAR(36) PRIMARY KEY, audio_ref VARCHAR(1024) NOT NULL, "
                "video_ref VARCHAR(1024) NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO session_recordings (id, audio_ref, video_ref) VALUES "
                "('audio-only', 'objects/audio-only.webm', NULL), "
                "('audio-video', 'objects/audio-video.webm', 'objects/video.webm')"
            )
        )


async def _run_migration(engine: AsyncEngine, migration, direction: str) -> None:
    async with engine.begin() as connection:
        def run(sync_connection) -> None:
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                getattr(migration, direction)()

        await connection.run_sync(run)


@pytest.mark.asyncio
async def test_source_inventory_migration_backfills_only_explicit_legacy_sources(
    async_engine: AsyncEngine,
) -> None:
    migration = _source_inventory_migration()
    assert migration.down_revision == PREVIOUS_REVISION
    await _seed_legacy_recordings(async_engine)
    await _run_migration(async_engine, migration, "upgrade")

    async with async_engine.connect() as connection:
        presence = (
            await connection.execute(
                text("SELECT id, video_presence FROM session_recordings ORDER BY id")
            )
        ).all()
        sources = (
            await connection.execute(
                text(
                    "SELECT recording_id, kind, object_ref, mime_type, video_offset_ms, "
                    "quality_label FROM recording_media_sources ORDER BY recording_id, kind"
                )
            )
        ).all()

    assert presence == [("audio-only", "unknown"), ("audio-video", "unknown")]
    assert {(row.recording_id, row.kind, row.object_ref) for row in sources} == {
        ("audio-only", "audio", "objects/audio-only.webm"),
        ("audio-video", "audio", "objects/audio-video.webm"),
        ("audio-video", "video", "objects/video.webm"),
    }
    assert all(row.mime_type is None and row.video_offset_ms is None for row in sources)
    assert all(row.quality_label == "Original" for row in sources)


@pytest.mark.asyncio
async def test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills(
    async_engine: AsyncEngine,
) -> None:
    migration = _source_inventory_migration()
    await _seed_legacy_recordings(async_engine)
    await _run_migration(async_engine, migration, "upgrade")
    await _run_migration(async_engine, migration, "downgrade")

    async with async_engine.connect() as connection:
        refs = (
            await connection.execute(
                text("SELECT id, audio_ref, video_ref FROM session_recordings ORDER BY id")
            )
        ).all()
        tables = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
    assert refs == [
        ("audio-only", "objects/audio-only.webm", None),
        ("audio-video", "objects/audio-video.webm", "objects/video.webm"),
    ]
    assert "recording_media_sources" not in {row.name for row in tables}

    await _run_migration(async_engine, migration, "upgrade")
    async with async_engine.connect() as connection:
        count = await connection.scalar(text("SELECT COUNT(*) FROM recording_media_sources"))
    assert count == 3


@pytest.mark.asyncio
async def test_source_inventory_rejects_duplicate_recording_kind_and_reference(
    async_engine: AsyncEngine,
) -> None:
    migration = _source_inventory_migration()
    await _seed_legacy_recordings(async_engine)
    await _run_migration(async_engine, migration, "upgrade")

    with pytest.raises(IntegrityError):
        async with async_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO recording_media_sources "
                    "(id, recording_id, kind, object_ref, quality_label) "
                    "VALUES ('duplicate', 'audio-only', 'audio', "
                    "'objects/audio-only.webm', 'Original')"
                )
            )
