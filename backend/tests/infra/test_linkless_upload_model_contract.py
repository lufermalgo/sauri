from __future__ import annotations

import ast
from pathlib import Path

from app.infra import models
from app.ingestion.schemas import IngestionData


def test_meeting_meet_link_is_nullable() -> None:
    assert models.Meeting.__table__.c.meet_link.nullable is True


def test_ingestion_schema_accepts_web_upload_without_meet_link() -> None:
    data = IngestionData(
        meeting_id="synthetic-meeting-id",
        idempotency_key="synthetic-idempotency-key",
        capture_origin="web_upload",
        video_presence="absent",
        duration_seconds=1,
    )

    assert data.capture_origin == "web_upload"
    assert data.meet_link is None


def test_pending_object_deletion_model_has_scoped_unique_refs_and_no_foreign_keys() -> None:
    pending_model = getattr(models, "PendingObjectDeletion", None)
    assert pending_model is not None

    table = pending_model.__table__
    assert {"id", "cleanup_scope_hash", "object_ref"} <= set(table.c.keys())
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("cleanup_scope_hash", "object_ref") in unique_columns
    assert not table.foreign_keys


def test_contract_migration_is_the_only_successor_to_revision_010() -> None:
    migrations_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    successors: list[Path] = []
    for migration_path in migrations_dir.glob("*.py"):
        tree = ast.parse(migration_path.read_text(encoding="utf-8"))
        assignments = {
            target.id: ast.literal_eval(value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
            for value in [node.value]
            if target.id in {"revision", "down_revision"}
        }
        if assignments.get("down_revision") == "010_speaker_excerpt_reference":
            successors.append(migration_path)

    assert len(successors) == 1
    migration_source = successors[0].read_text(encoding="utf-8")
    assert "pending_object_deletions" in migration_source
    assert '"meet_link"' in migration_source
    assert "nullable=True" in migration_source
    assert "downgrade" in migration_source
    assert "cleanup_scope_hash" in migration_source
    assert "object_ref" in migration_source


def test_migration_downgrade_guards_pending_tasks_and_null_links() -> None:
    import importlib.util

    import pytest
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migrations_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    migration_path = next(
        path
        for path in migrations_dir.glob("*.py")
        if "pending_object_deletions" in path.read_text(encoding="utf-8")
    )
    spec = importlib.util.spec_from_file_location(migration_path.stem, migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, meet_link VARCHAR(512) NULL)")
        )
        connection.execute(
            text(
                "CREATE TABLE pending_object_deletions ("
                "id VARCHAR(36) PRIMARY KEY, cleanup_scope_hash VARCHAR(64) NOT NULL, "
                "object_ref VARCHAR(2048) NOT NULL, UNIQUE (cleanup_scope_hash, object_ref))"
            )
        )
        connection.execute(text("INSERT INTO meetings (id, meet_link) VALUES ('m1', NULL)"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            with pytest.raises(RuntimeError, match="null Meet links"):
                migration.downgrade()

            connection.execute(text("UPDATE meetings SET meet_link = 'https://meet.test'"))
            connection.execute(
                text(
                    "INSERT INTO pending_object_deletions "
                    "(id, cleanup_scope_hash, object_ref) VALUES ('d1', 'scope', 'ref')"
                )
            )
            with pytest.raises(RuntimeError, match="pending object cleanup tasks"):
                migration.downgrade()

            connection.execute(text("DELETE FROM pending_object_deletions"))
            migration.downgrade()

        assert not inspect(connection).has_table("pending_object_deletions")

    engine.dispose()
