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

import asyncio
import importlib.util
import inspect
import os
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import event, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command

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


def _load_migration_module() -> ModuleType:
    path = MIGRATIONS_DIR / MIGRATION_FILENAME
    spec = importlib.util.spec_from_file_location(
        MIGRATION_FILENAME.replace(".py", ""), path
    )
    assert spec is not None and spec.loader is not None
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
    def _table_names(sync_conn: Connection) -> set[str]:
        return set(sa_inspect(sync_conn).get_table_names())

    async with async_engine.connect() as conn:
        tables = await conn.run_sync(_table_names)

    for old_name, new_name in OLD_TO_NEW_TABLES.items():
        assert new_name in tables, f"expected table '{new_name}' in models.py"
        assert old_name not in tables, f"table '{old_name}' should be gone from models.py"


@pytest.mark.asyncio
async def test_orm_schema_meetings_has_english_columns(async_engine: AsyncEngine) -> None:
    def _columns(sync_conn: Connection) -> set[str]:
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
    def _columns(sync_conn: Connection) -> set[str]:
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


def _source_inventory_migration() -> ModuleType:
    path = MIGRATIONS_DIR / "009_recording_media_sources.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "009_recording_media_sources"
    return module


def test_source_inventory_migration_selects_exact_revision_independent_of_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_glob = Path.glob

    def sibling_first_migration_glob(path: Path, pattern: str) -> list[Path]:
        paths = list(original_glob(path, pattern))
        if path == MIGRATIONS_DIR and pattern == "*.py":
            return sorted(
                paths,
                key=lambda candidate: candidate.name
                != "009_speaker_review_idempotency_receipts.py",
            )
        return paths

    monkeypatch.setattr(Path, "glob", sibling_first_migration_glob)

    assert _source_inventory_migration().revision == "009_recording_media_sources"


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


async def _run_migration(
    engine: AsyncEngine, migration: ModuleType, direction: str
) -> None:
    async with engine.begin() as connection:
        def run(sync_connection: Connection) -> None:
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


@pytest.mark.asyncio
async def test_speaker_receipt_upgrade_records_full_revision_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade to the receipts revision in a database created for this test only."""
    admin_url = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("requires an isolated PostgreSQL admin URL in SAURI_MIGRATION_TEST_ADMIN_URL")

    parsed_url = make_url(admin_url)
    database_name = f"sauri_migration_qa_{uuid4().hex}"
    connect_args: dict[str, str | int] = {
        "user": parsed_url.username or "",
        "database": parsed_url.database or "postgres",
    }
    if parsed_url.password is not None:
        connect_args["password"] = parsed_url.password
    if parsed_url.host is not None:
        connect_args["host"] = parsed_url.host
    if parsed_url.port is not None:
        connect_args["port"] = parsed_url.port

    admin_connection = await asyncpg.connect(**connect_args)
    try:
        await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
        test_url = parsed_url.set(database=database_name).render_as_string(hide_password=False)
        monkeypatch.setenv("DATABASE_URL", test_url)
        config = Config(str(MIGRATIONS_DIR.parents[1] / "alembic.ini"))

        await asyncio.to_thread(command.upgrade, config, AGGREGATE_REVISION)
        await asyncio.to_thread(command.upgrade, config, SPEAKER_REVIEW_RECEIPTS_REVISION)

        async with (
            asyncpg.create_pool(**(connect_args | {"database": database_name})) as pool,
            pool.acquire() as connection,
        ):
            recorded_revision = await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            version_width = await connection.fetchval(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
            )
            receipts_table_exists = await connection.fetchval(
                "SELECT to_regclass('public.speaker_review_idempotency_receipts') IS NOT NULL"
            )

        assert recorded_revision == SPEAKER_REVIEW_RECEIPTS_REVISION
        assert len(recorded_revision) == 39
        assert version_width == 39
        assert receipts_table_exists
    finally:
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()


@pytest.mark.asyncio
async def test_speaker_receipt_upgrade_failure_rolls_back_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receipt-table collision rolls back the preceding version-column widening."""
    admin_url = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("requires an isolated PostgreSQL admin URL in SAURI_MIGRATION_TEST_ADMIN_URL")

    parsed_url = make_url(admin_url)
    database_name = f"sauri_migration_qa_{uuid4().hex}"
    connect_args: dict[str, str | int] = {
        "user": parsed_url.username or "",
        "database": parsed_url.database or "postgres",
    }
    if parsed_url.password is not None:
        connect_args["password"] = parsed_url.password
    if parsed_url.host is not None:
        connect_args["host"] = parsed_url.host
    if parsed_url.port is not None:
        connect_args["port"] = parsed_url.port

    admin_connection = await asyncpg.connect(**connect_args)
    statements: list[str] = []

    def record_migration_statement(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if connection.engine.url.database == database_name:
            statements.append(" ".join(statement.split()).upper())

    try:
        await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
        test_url = parsed_url.set(database=database_name).render_as_string(hide_password=False)
        monkeypatch.setenv("DATABASE_URL", test_url)
        config = Config(str(MIGRATIONS_DIR.parents[1] / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, AGGREGATE_REVISION)

        async with (
            asyncpg.create_pool(**(connect_args | {"database": database_name})) as pool,
            pool.acquire() as connection,
        ):
            await connection.execute(
                "CREATE TABLE speaker_review_idempotency_receipts "
                "(fixture_marker TEXT NOT NULL)"
            )
            await connection.execute(
                "INSERT INTO speaker_review_idempotency_receipts (fixture_marker) "
                "VALUES ('synthetic-collision-preserved')"
            )

        event.listen(Engine, "before_cursor_execute", record_migration_statement)
        try:
            with pytest.raises(DBAPIError) as migration_error:
                await asyncio.to_thread(
                    command.upgrade, config, SPEAKER_REVIEW_RECEIPTS_REVISION
                )
        finally:
            event.remove(Engine, "before_cursor_execute", record_migration_statement)

        assert "speaker_review_idempotency_receipts" in str(migration_error.value)
        async with (
            asyncpg.create_pool(**(connect_args | {"database": database_name})) as pool,
            pool.acquire() as connection,
        ):
            recorded_revision = await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            version_width = await connection.fetchval(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
            )
            collision_columns = await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'speaker_review_idempotency_receipts' "
                "ORDER BY ordinal_position"
            )
            collision_rows = await connection.fetch(
                "SELECT fixture_marker FROM speaker_review_idempotency_receipts"
            )

        alteration_index = next(
            (
                index
                for index, statement in enumerate(statements)
                if "ALTER TABLE ALEMBIC_VERSION" in statement
                and "ALTER COLUMN VERSION_NUM TYPE VARCHAR(39)" in statement
            ),
            None,
        )
        collision_index = next(
            (
                index
                for index, statement in enumerate(statements)
                if "CREATE TABLE SPEAKER_REVIEW_IDEMPOTENCY_RECEIPTS" in statement
            ),
            None,
        )

        assert recorded_revision == AGGREGATE_REVISION
        assert version_width == 32
        assert [row["column_name"] for row in collision_columns] == ["fixture_marker"]
        assert [row["fixture_marker"] for row in collision_rows] == [
            "synthetic-collision-preserved"
        ]
        assert alteration_index is not None, (
            "expected the migration's alembic_version widening DDL; observed: "
            f"{statements!r}"
        )
        assert collision_index is not None, (
            "expected the migration's receipt-table CREATE DDL; observed: "
            f"{statements!r}"
        )
        assert alteration_index < collision_index
    finally:
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()


# Alembic graph contract for the two published 009 branches (T-3, issue #404).
RECORDING_MEDIA_REVISION = "009_recording_media_sources"
SPEAKER_REVIEW_RECEIPTS_REVISION = "009_speaker_review_idempotency_receipts"
AGGREGATE_REVISION = "008_speaker_review_aggregate"
RECONCILIATION_REVISION = "010_speaker_excerpt_reference"
LINKLESS_REVISION = "011_linkless_cleanup"
DIARIZATION_GENERATIONS_REVISION = "012_diarization_generations"
MANUAL_RECOVERY_REVISION = "013_manual_recovery_persistence"
SUMMARY_TEMPLATES_REVISION = "014_meeting_summaries_templates"
LEGACY_PREDECESSOR_REVISION = "007_rename_schema_to_english"
LEGACY_PREDECESSOR_PARENT = "006_add_titulo_reunion"


def _migration_script() -> ScriptDirectory:
    config = Config(str(MIGRATIONS_DIR.parents[1] / "alembic.ini"))
    return ScriptDirectory.from_config(config)


def _load_published_migration(filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_migration_revision_ids_and_immediate_parent_are_preserved() -> None:
    script = _migration_script()
    published_migrations = (
        ("009_recording_media_sources.py", RECORDING_MEDIA_REVISION),
        (
            "009_speaker_review_idempotency_receipts.py",
            SPEAKER_REVIEW_RECEIPTS_REVISION,
        ),
    )

    for filename, expected_revision in published_migrations:
        migration = _load_published_migration(filename)
        assert migration.revision == expected_revision
        assert migration.down_revision == AGGREGATE_REVISION

        graph_revision = script.get_revision(expected_revision)
        assert graph_revision is not None
        assert graph_revision.revision == expected_revision
        assert graph_revision.down_revision == AGGREGATE_REVISION


def test_summary_head_follows_manual_recovery_generations_and_009_reconciliation() -> None:
    script = _migration_script()
    heads = script.get_heads()

    assert heads == [SUMMARY_TEMPLATES_REVISION], (
        "Alembic graph must have one summary templates head; "
        f"found {heads!r}"
    )
    summary_migration = script.get_revision(heads[0])
    assert summary_migration.down_revision == MANUAL_RECOVERY_REVISION
    recovery_migration = script.get_revision(MANUAL_RECOVERY_REVISION)
    assert recovery_migration.down_revision == DIARIZATION_GENERATIONS_REVISION
    generation_migration = script.get_revision(DIARIZATION_GENERATIONS_REVISION)
    assert generation_migration.down_revision == LINKLESS_REVISION

    linkless_migration = script.get_revision(LINKLESS_REVISION)
    assert linkless_migration.down_revision == RECONCILIATION_REVISION

    reconciliation = script.get_revision(RECONCILIATION_REVISION)
    assert set(cast(tuple[str, ...], reconciliation.down_revision)) == {
        RECORDING_MEDIA_REVISION,
        SPEAKER_REVIEW_RECEIPTS_REVISION,
    }, "the reconciliation revision must directly merge both existing 009 revisions"


def test_head_ancestry_contains_both_009_branches_and_008() -> None:
    script = _migration_script()
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one converged Alembic head, found {heads!r}"

    ancestry = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }
    assert {
        RECORDING_MEDIA_REVISION,
        SPEAKER_REVIEW_RECEIPTS_REVISION,
        AGGREGATE_REVISION,
    } <= ancestry, f"head ancestry must include both 009 branches and 008; found {ancestry!r}"


def test_each_009_state_has_a_structural_forward_path_through_sibling_to_head() -> None:
    script = _migration_script()
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one converged Alembic head, found {heads!r}"
    head = heads[0]

    for current_revision, sibling_revision in (
        (RECORDING_MEDIA_REVISION, SPEAKER_REVIEW_RECEIPTS_REVISION),
        (SPEAKER_REVIEW_RECEIPTS_REVISION, RECORDING_MEDIA_REVISION),
    ):
        planned = {
            step.revision.revision
            for step in script._upgrade_revs(head, current_revision)
        }
        assert head in planned, f"upgrade from {current_revision} must reach reconciliation head"
        assert sibling_revision in planned, (
            f"upgrade from {current_revision} must include missing sibling "
            f"{sibling_revision}; planned {planned!r}"
        )


def test_revision_traversal_remains_continuous_before_008_and_through_head() -> None:
    script = _migration_script()
    before_008 = {
        revision.revision
        for revision in script.iterate_revisions(AGGREGATE_REVISION, LEGACY_PREDECESSOR_PARENT)
    }
    assert {AGGREGATE_REVISION, LEGACY_PREDECESSOR_REVISION} <= before_008

    heads = script.get_heads()
    assert len(heads) == 1, f"expected one converged Alembic head, found {heads!r}"
    through_head = {revision.revision for revision in script.iterate_revisions(heads[0], "base")}
    assert {
        LEGACY_PREDECESSOR_PARENT,
        LEGACY_PREDECESSOR_REVISION,
        AGGREGATE_REVISION,
        RECORDING_MEDIA_REVISION,
        SPEAKER_REVIEW_RECEIPTS_REVISION,
    } <= through_head, f"expected uninterrupted history through reconciliation; found {through_head!r}"


@pytest.mark.asyncio
async def test_speaker_review_receipt_migration_preserves_persisted_contract(
    async_engine: AsyncEngine,
) -> None:
    path = MIGRATIONS_DIR / "009_speaker_review_idempotency_receipts.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == SPEAKER_REVIEW_RECEIPTS_REVISION
    assert migration.down_revision == AGGREGATE_REVISION

    async with async_engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS speaker_review_idempotency_receipts"))
    await _run_migration(async_engine, migration, "upgrade")

    def inspect_receipt_contract(
        sync_connection: Connection,
    ) -> tuple[
        dict[str, tuple[str, bool]],
        set[str],
        set[tuple[str | None, tuple[str, ...]]],
        set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]],
    ]:
        inspector = sa_inspect(sync_connection)
        columns = {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspector.get_columns("speaker_review_idempotency_receipts")
        }
        primary_key = set(
            cast(
                tuple[str, ...],
                inspector.get_pk_constraint("speaker_review_idempotency_receipts")[
                    "constrained_columns"
                ],
            )
        )
        unique_constraints = {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(
                "speaker_review_idempotency_receipts"
            )
        }
        foreign_keys = {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                cast(str | None, foreign_key["options"].get("ondelete")),
            )
            for foreign_key in inspector.get_foreign_keys(
                "speaker_review_idempotency_receipts"
            )
        }
        return columns, primary_key, unique_constraints, foreign_keys

    async with async_engine.connect() as connection:
        columns, primary_key, unique_constraints, foreign_keys = await connection.run_sync(
            inspect_receipt_contract
        )

    assert columns == {
        "id": ("VARCHAR(36)", False),
        "review_id": ("VARCHAR(36)", False),
        "item_id": ("VARCHAR(36)", False),
        "idempotency_key": ("VARCHAR(256)", False),
        "request_hash": ("VARCHAR(64)", False),
        "response": ("JSON", False),
    }
    assert primary_key == {"id"}
    assert unique_constraints == {
        ("uq_review_idempotency_key", ("review_id", "idempotency_key"))
    }
    assert foreign_keys == {
        (("review_id",), "speaker_reviews", ("id",), "CASCADE"),
        (("item_id",), "speaker_review_items", ("id",), "CASCADE"),
    }
