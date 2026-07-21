"""Tests for the Language_Regression_Check tool (_tools/check_english_only.py).

See .spectra/specs/english-codebase-standard/design.md > Propiedades de
Correctitud > Propiedad 5, and tasks.md > Fase 1 > Tarea 1.1/1.2.
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


def test_flags_accented_identifiers(tmp_path: Path) -> None:
    accented_file = tmp_path / "example_accented.ts"
    accented_file.write_text("export function añadirNota() {}\n")  # spanish-sample-data

    result = run_check(accented_file)

    assert result.returncode == 1
    assert "añadirNota" in result.stdout  # spanish-sample-data
