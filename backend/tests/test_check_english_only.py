"""Tests for the Language_Regression_Check tool (_tools/check_english_only.py).

These tests verify the English-only identifier policy documented in AGENTS.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "_tools" / "check_english_only.py"


def run_check(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
    )


def test_reports_one_retired_spanish_identifier(tmp_path: Path) -> None:
    spanish_file = tmp_path / "example_spanish.py"
    spanish_file.write_text("def obtener_reunion():\n    pass\n")  # spanish-sample-data

    result = run_check(spanish_file)

    assert result.returncode == 1
    assert f"{spanish_file}:1:" in result.stdout
    assert "obtener_reunion" in result.stdout  # spanish-sample-data


def test_zero_findings_for_english_only_file(tmp_path: Path) -> None:
    english_file = tmp_path / "example_english.py"
    english_file.write_text("def get_meeting():\n    pass\n")

    result = run_check(english_file)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_excludes_alembic_migration_files(tmp_path: Path) -> None:
    """Migration scripts legitimately rename FROM old Spanish names — a
    rename migration must name both sides, so it's excluded rather than
    treated as leftover Spanish code (design.md's "excluded paths" concept,
    extended during Fase 2 implementation to cover backend/alembic/versions/
    and files named test_migration.py, which exist to test that rename)."""
    versions_dir = tmp_path / "backend" / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    migration_file = versions_dir / "007_rename_schema_to_english.py"
    migration_file.write_text('op.rename_table("reuniones", "meetings")\n')  # spanish-sample-data

    result = run_check(migration_file)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_excludes_ui_copy_module(tmp_path: Path) -> None:
    """User-facing text is product-language content, not identifiers: it lives
    in frontend/src/copy/ and is the only frontend place where it is allowed."""
    copy_dir = tmp_path / "frontend" / "src" / "copy"
    copy_dir.mkdir(parents=True)
    copy_file = copy_dir / "es.ts"
    copy_file.write_text('export const submit = "Subir grabación";\n')  # spanish-sample-data

    other_file = tmp_path / "frontend" / "src" / "View.tsx"
    other_file.write_text('const label = "Subir grabación";\n')  # spanish-sample-data

    assert run_check(copy_file).returncode == 0
    assert run_check(other_file).returncode == 1


def test_excludes_test_migration_files(tmp_path: Path) -> None:
    test_migration_file = tmp_path / "backend" / "tests" / "test_migration.py"
    test_migration_file.parent.mkdir(parents=True)
    test_migration_file.write_text('OLD_TO_NEW = {"reuniones": "meetings"}\n')  # spanish-sample-data

    result = run_check(test_migration_file)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_flags_accented_identifiers(tmp_path: Path) -> None:
    accented_file = tmp_path / "example_accented.ts"
    accented_file.write_text("export function añadirNota() {}\n")  # spanish-sample-data

    result = run_check(accented_file)

    assert result.returncode == 1
    assert "añadirNota" in result.stdout  # spanish-sample-data


def test_excludes_ui_copy_module(tmp_path: Path) -> None:
    copy_dir = tmp_path / "backend" / "app" / "copy"
    copy_dir.mkdir(parents=True)
    copy_file = copy_dir / "templates_es.py"
    copy_file.write_text('TITLE = "Identificación del tema principal"\n')  # spanish-sample-data
    assert run_check(copy_file).returncode == 0
    logic_file = tmp_path / "backend" / "app" / "logic.py"
    logic_file.write_text('TITLE = "Identificación del tema principal"\n')  # spanish-sample-data
    assert run_check(logic_file).returncode == 1


def test_scanner_does_not_flag_its_own_prohibited_vocabulary() -> None:
    assert run_check(CHECK_SCRIPT).returncode == 0
