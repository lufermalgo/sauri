"""--check does not install, build or create state when the native engine is absent."""

import os
import subprocess
from pathlib import Path


def test_check_is_read_only(tmp_path: Path) -> None:
    root = Path(__file__).parents[3]
    destination = tmp_path / "absent"
    result = subprocess.run(
        ["bash", str(root / "scripts/engines/install-llm-engine.sh"), "--check"],
        cwd=root, env={**os.environ, "SAURI_LLM_INSTALL_DIR": str(destination)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "not installed" in result.stderr or "Requires Apple silicon" in result.stderr
    assert not destination.exists()
