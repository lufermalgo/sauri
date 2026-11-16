"""`native-engines.sh stop` ends the helper programs the engine left behind (#1166)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "engines" / "native-engines.sh"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_stop_ends_a_helper_that_outlived_the_server(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    # A stand-in that looks like the ASR server to the script, with a long-running helper child.
    server = subprocess.Popen([
        "sh", "-c", f"sleep 120 & echo $! > {child_pid_file}; wait",
        "uvicorn", "native_main:app", "--port", "8001",
    ])
    try:
        deadline = time.monotonic() + 10
        while not child_pid_file.exists() or not child_pid_file.read_text().strip():
            assert time.monotonic() < deadline
            time.sleep(0.05)
        helper = int(child_pid_file.read_text())
        state = tmp_path / "state"
        state.mkdir()
        (state / "asr.pid").write_text(f"{server.pid}\n")

        result = subprocess.run(
            ["bash", str(SCRIPT), "stop", "asr"], env={**os.environ, "SAURI_NATIVE_ENGINE_STATE_DIR": str(state)},
            capture_output=True, text=True, timeout=60, check=False,
        )
        server.wait(timeout=10)

        assert result.returncode == 0, result.stderr
        assert "stopped" in result.stdout and f"helper process {helper} ended" in result.stdout
        deadline = time.monotonic() + 5
        while alive(helper) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not alive(helper)
    finally:
        server.kill()
