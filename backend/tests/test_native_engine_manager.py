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
    assert "bash _tools/ensure-native-engine-credentials.sh" in makefile


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


def test_diarization_installs_matplotlib_runtime_dependency() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    requirements = (REPO_ROOT / "backend" / "diar-engine" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "'matplotlib==3.9.2'" in makefile
    assert "matplotlib==3.9.2" in requirements


def test_native_engine_manager_binds_loopback_only() -> None:
    manager = MANAGER.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in manager
    assert "--host 0.0.0.0" not in manager


def test_worker_mounts_the_native_engine_token_read_only() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    worker_config = compose.split("  worker:", maxsplit=1)[1].split("  # --- PostgreSQL ---", maxsplit=1)[0]
    assert "SAURI_ENGINE_TOKEN_FILE=/run/secrets/sauri_engine_token" in worker_config
    assert "/run/secrets/sauri_engine_token:ro" in worker_config
    assert "SAURI_RECORDING_CAPABILITY_KEY_FILE=/run/secrets/recording_capability_key" in worker_config
    assert "/run/secrets/recording_capability_key:ro" in worker_config


def test_make_engines_up_and_compose_bringup_provision_shared_credentials() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    compose_bringup = (REPO_ROOT / "_tools" / "compose-bringup.sh").read_text(encoding="utf-8")
    provisioner = '_tools/ensure-native-engine-credentials.sh'
    assert provisioner in makefile.split("engines-up:", maxsplit=1)[1].split("engines-down:", maxsplit=1)[0]
    assert provisioner in compose_bringup


def test_credential_provisioner_creates_shared_private_files_and_preserves_existing_values(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".config" / "sauri"
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    provisioner = REPO_ROOT / "_tools" / "ensure-native-engine-credentials.sh"

    provisioned = subprocess.run(
        ["bash", str(provisioner)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert provisioned.returncode == 0, provisioned.stderr
    token = config_dir / "engine_token"
    capability_key = config_dir / "recording_capability_key"
    assert token.is_file() and token.stat().st_mode & 0o777 == 0o600
    assert capability_key.is_file() and capability_key.stat().st_mode & 0o777 == 0o600
    assert token.read_text(encoding="utf-8").strip()
    assert capability_key.read_text(encoding="utf-8").strip()

    token.write_text("preserved-engine-token", encoding="utf-8")
    capability_key.write_text("preserved-capability-key", encoding="utf-8")
    token.chmod(0o644)
    capability_key.chmod(0o644)
    repeated = subprocess.run(
        ["bash", str(provisioner)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert token.read_text(encoding="utf-8") == "preserved-engine-token"
    assert capability_key.read_text(encoding="utf-8") == "preserved-capability-key"
    assert token.stat().st_mode & 0o777 == 0o600
    assert capability_key.stat().st_mode & 0o777 == 0o600


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
    (token_file.parent / "recording_capability_key").write_text(
        "synthetic-capability-key", encoding="utf-8"
    )
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
