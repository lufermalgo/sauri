"""RED migration contract for the durable pending-object deletion ledger."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
PENDING_TABLE = "pending_object_deletions"


def _migration_for_pending_table() -> tuple[Path, ModuleType]:
    candidates = [
        path
        for path in MIGRATIONS_DIR.glob("*.py")
        if PENDING_TABLE in path.read_text(encoding="utf-8")
    ]
    assert len(candidates) == 1, (
        "exactly one sequential Alembic migration must create the pending "
        f"deletion table; found {candidates}"
    )
    path = candidates[0]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return path, module


def test_pending_deletion_migration_chains_after_current_head() -> None:
    _, migration = _migration_for_pending_table()

    assert migration.revision
    assert migration.down_revision == "010_speaker_excerpt_reference"
    assert hasattr(migration, "upgrade")
    assert hasattr(migration, "downgrade")


def test_pending_deletion_migration_has_scope_ref_uniqueness_and_no_foreign_keys() -> None:
    path, _ = _migration_for_pending_table()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    table_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_table"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == PENDING_TABLE
    ]
    assert len(table_calls) == 1
    table_source = ast.get_source_segment(source, table_calls[0])
    assert table_source is not None
    assert "cleanup_scope_hash" in table_source
    assert "object_ref" in table_source
    assert "UniqueConstraint" in table_source
    assert "ForeignKey" not in table_source


def test_downgrade_refuses_while_pending_object_tasks_exist() -> None:
    path, _ = _migration_for_pending_table()
    source = path.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", maxsplit=1)[1]

    assert PENDING_TABLE in downgrade
    assert "SELECT" in downgrade.upper() or "select(" in downgrade
    assert "raise" in downgrade
    assert downgrade.index("raise") < downgrade.index("drop_table")
