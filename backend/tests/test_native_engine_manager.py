"""Tests for safe lifecycle management of native engine servers."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGER = REPO_ROOT / "_tools" / "native-engines.sh"


def test_makefile_exposes_native_engine_lifecycle_targets() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("engines-up", "engines-down", "engines-status", "engines-install"):
        assert f"{target}:" in makefile
    assert "$(HOME)/.config/sauri/engine_token" in makefile
    assert "secrets.token_urlsafe(32)" in makefile


def test_native_diarization_install_pins_compatible_torch_pair() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "'torch==2.5.1'" in makefile
    assert "'torchaudio==2.5.1'" in makefile


def test_diarization_pins_huggingface_hub_compatible_with_pyannote() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    requirements = (REPO_ROOT / "backend" / "diar-engine" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "'huggingface_hub==0.24.7'" in makefile
    assert "huggingface_hub==0.24.7" in requirements


def test_native_engine_manager_binds_loopback_only() -> None:
    manager = MANAGER.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in manager
    assert "--host 0.0.0.0" not in manager


def test_worker_mounts_the_native_engine_token_read_only() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    worker_config = compose.split("  worker:", maxsplit=1)[1].split("  # --- PostgreSQL ---", maxsplit=1)[0]
    assert "SAURI_ENGINE_TOKEN_FILE=/run/secrets/sauri_engine_token" in worker_config
    assert "/run/secrets/sauri_engine_token:ro" in worker_config


def test_manager_starts_reports_and_stops_exact_server_pids(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/bin/bash\n"
        "port=8001\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == 8002 ]]; then port=8002; fi\n"
        "done\n"
        "exec -a \"python -m uvicorn native_main:app --port $port\" sleep 60\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    token_file = tmp_path / ".config" / "sauri" / "engine_token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("synthetic-token", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "SAURI_NATIVE_ENGINE_PYTHON": str(fake_python),
        "SAURI_NATIVE_ENGINE_STATE_DIR": str(tmp_path / "state"),
    }

    started = subprocess.run(
        ["bash", str(MANAGER), "start", "asr"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr

    status = subprocess.run(
        ["bash", str(MANAGER), "status", "asr"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert status.returncode == 0, status.stdout + status.stderr
    assert "running" in status.stdout.lower()

    stopped = subprocess.run(
        ["bash", str(MANAGER), "stop", "asr"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert "stopped" in stopped.stdout.lower()


def test_manager_refuses_to_signal_a_pid_that_is_not_its_engine(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    unrelated = subprocess.Popen(["sleep", "60"])
    (state_dir / "asr.pid").write_text(f"{unrelated.pid}\n", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "SAURI_NATIVE_ENGINE_STATE_DIR": str(state_dir),
    }
    try:
        stopped = subprocess.run(
            ["bash", str(MANAGER), "stop", "asr"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert stopped.returncode == 1
        assert "refusing to signal" in stopped.stderr.lower()
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
