"""Wiring of the host service: credentials, Compose mount, process manager and a real uvicorn run."""

from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from conftest import BACKEND

REPO_ROOT = BACKEND.parent
MANAGER = REPO_ROOT / "scripts" / "engines" / "native-engines.sh"
PROVISIONER = REPO_ROOT / "scripts" / "engines" / "ensure-native-engine-credentials.sh"
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False, timeout=60)


# --- credentials ------------------------------------------------------------------------------------


def test_provisioner_creates_a_private_management_token_distinct_from_the_engine_token(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "PATH": SAFE_PATH}
    first = run(["bash", str(PROVISIONER)], env)
    assert first.returncode == 0, first.stderr
    config = tmp_path / ".config" / "sauri"
    token = (config / "management_token").read_text().strip()
    assert len(token) >= 32 and token != (config / "engine_token").read_text().strip()
    assert stat.S_IMODE((config / "management_token").stat().st_mode) == 0o600
    assert token not in first.stdout + first.stderr
    (config / "management_token").write_text("preserved-token\n")
    (config / "management_token").chmod(0o644)
    assert run(["bash", str(PROVISIONER)], env).returncode == 0
    assert (config / "management_token").read_text().strip() == "preserved-token"
    assert stat.S_IMODE((config / "management_token").stat().st_mode) == 0o600


# --- Compose ----------------------------------------------------------------------------------------


def _compose() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))[
        "services"
    ]
    return services


def test_the_management_token_is_mounted_read_only_in_the_api_and_nowhere_else() -> None:
    services = _compose()
    api = services["api"]
    assert any(
        mount.endswith("/.config/sauri/management_token:/run/secrets/management_token:ro") for mount in api["volumes"]
    )
    assert "MANAGEMENT_TOKEN_FILE=/run/secrets/management_token" in api["environment"]
    assert any(item.startswith("HOST_ENGINE_URL=") and ":8005" in item for item in api["environment"])
    for name, service in services.items():
        if name == "api":
            continue
        text = yaml.safe_dump(service)
        assert "management_token" not in text and "MANAGEMENT_TOKEN" not in text and "HOST_ENGINE_URL" not in text, name


def test_the_worker_receives_exactly_its_previous_credential_files() -> None:
    targets = {mount.rsplit(":", 2)[1] for mount in _compose()["worker"]["volumes"]}
    assert targets == {
        f"/run/secrets/{name}"
        for name in (
            "sauri_engine_token", "recording_capability_key", "database_password", "queue_password",
            "object_store_access_key", "object_store_secret_key",
        )
    }


def test_compose_publishes_no_host_service_port() -> None:
    for service in _compose().values():
        assert not any("8005" in str(port) for port in service.get("ports", []))


# --- process manager --------------------------------------------------------------------------------


@pytest.fixture
def manager_env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / ".config" / "sauri"
    config.mkdir(parents=True)
    (config / "management_token").write_text("synthetic-management-token\n")
    fake = tmp_path / "fake-python"
    fake.write_text(
        "#!/bin/bash\n"
        f'echo "$@" > "{tmp_path}/args.txt"\n'
        f'echo "$PYTHONPATH" > "{tmp_path}/pythonpath.txt"\n'
        'exec -a "python -m uvicorn native_main:app --port 8005" sleep 60\n'
    )
    fake.chmod(0o755)
    return {
        "PATH": SAFE_PATH,
        "HOME": str(tmp_path),
        "SAURI_HOST_ENGINE_PYTHON": str(fake),
        "SAURI_NATIVE_ENGINE_STATE_DIR": str(tmp_path / "state"),
    }


def test_manager_starts_reports_and_stops_the_host_service_on_loopback_only(
    manager_env: dict[str, str], tmp_path: Path
) -> None:
    started = run(["bash", str(MANAGER), "start", "host"], manager_env)
    try:
        assert started.returncode == 0, started.stderr
        status = run(["bash", str(MANAGER), "status", "host"], manager_env)
        assert status.returncode == 0 and "running" in status.stdout and "8005" in status.stdout
        args = (tmp_path / "args.txt").read_text()
        assert "--host 127.0.0.1" in args and "--port 8005" in args and "--no-access-log" in args
        assert "0.0.0.0" not in args and "backend/host-engine" in args
        assert "backend/engine-common" in (tmp_path / "pythonpath.txt").read_text()
    finally:
        stopped = run(["bash", str(MANAGER), "stop", "host"], manager_env)
    assert stopped.returncode == 0 and "stopped" in stopped.stdout


def test_the_host_service_needs_only_the_management_token(manager_env: dict[str, str], tmp_path: Path) -> None:
    config = tmp_path / ".config" / "sauri"
    assert not (config / "engine_token").exists() and not (config / "object_store_access_key").exists()
    try:
        assert run(["bash", str(MANAGER), "start", "host"], manager_env).returncode == 0
    finally:
        run(["bash", str(MANAGER), "stop", "host"], manager_env)


def test_the_host_service_refuses_to_start_without_its_token(manager_env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / ".config" / "sauri" / "management_token").unlink()
    refused = run(["bash", str(MANAGER), "start", "host"], manager_env)
    assert refused.returncode == 1 and "Management token missing" in refused.stderr
    assert "synthetic" not in refused.stdout + refused.stderr


def test_the_other_engines_still_require_the_engine_token_and_not_the_management_token(
    manager_env: dict[str, str], tmp_path: Path
) -> None:
    refused = run(["bash", str(MANAGER), "start", "asr"], manager_env)
    assert refused.returncode == 1 and "Native engine token missing" in refused.stderr


def test_status_all_lists_the_host_service(manager_env: dict[str, str]) -> None:
    status = run(["bash", str(MANAGER), "status", "all"], manager_env)
    assert "host stopped" in status.stdout and "ASR stopped" in status.stdout


def test_makefile_installs_the_host_service_and_engines_commands_cover_it() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "bash scripts/engines/install-host-engine.sh" in makefile
    assert "native-engines.sh status all" in makefile and "native-engines.sh start all" in makefile


def test_installer_check_changes_nothing_and_fails_without_the_venv(tmp_path: Path) -> None:
    env = {"PATH": SAFE_PATH, "HOME": str(tmp_path)}
    result = run(["bash", str(REPO_ROOT / "scripts" / "engines" / "install-host-engine.sh"), "--check"], env)
    assert result.returncode == 1 and "no changes made" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_requirements_are_service_only() -> None:
    lines = (BACKEND / "host-engine" / "requirements-native.txt").read_text().split()
    assert [line.split(">=")[0] for line in lines] == ["fastapi", "uvicorn[standard]", "httpx"]


# --- a real uvicorn process -------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_real_server_keeps_secret_bodies_out_of_every_output_and_listens_on_loopback_only(tmp_path: Path) -> None:
    token_file = tmp_path / "management_token"
    token_file.write_text("synthetic-management-token\n")
    port = _free_port()
    out = tmp_path / "server.log"
    env = {
        "PATH": SAFE_PATH,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(BACKEND / "engine-common"),
        "SAURI_MANAGEMENT_TOKEN_FILE": str(token_file),
        "SAURI_SECRET_STORE": "file",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    key = "KEY-real-server-probe-9f8e7d6c5b4a"
    auth = {"Authorization": "Bearer synthetic-management-token"}
    with out.open("w") as log:
        # Access logging is left ON here: even then no body, key or token may reach the output.
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "native_main:app", "--app-dir", str(BACKEND / "host-engine"),
             "--host", "127.0.0.1", "--port", str(port)],
            env=env, stdout=log, stderr=subprocess.STDOUT, cwd=tmp_path,
        )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health", headers=auth, timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("host service did not start")
        ref = "sauri/owner-1/provider-1"
        put = httpx.put(f"{base}/v1/secrets/{ref}", json={"key": key, "origin": "https://api.example.com"},
                        headers=auth, timeout=5)
        assert put.status_code == 200 and key not in put.text
        assert httpx.put(f"{base}/v1/secrets/{ref}", json={"key": key, "origin": 5}, headers=auth).status_code == 422
        assert httpx.put(f"{base}/v1/secrets/{ref}", json={"key": key}, headers={"Authorization": "Bearer x"}
                         ).status_code == 401
        assert httpx.delete(f"{base}/v1/secrets/{ref}", headers=auth).status_code == 204
        if shutil.which("lsof"):
            listing = subprocess.run(
                ["lsof", "-nP", "-a", "-p", str(process.pid), "-iTCP", "-sTCP:LISTEN"],
                capture_output=True, text=True, check=False,
            ).stdout
            assert f"127.0.0.1:{port}" in listing and f"*:{port}" not in listing and "0.0.0.0" not in listing
    finally:
        process.terminate()
        process.wait(timeout=10)
    output = out.read_text()
    assert "PUT" in output  # the access log is on, so the request lines were available to leak
    assert key not in output and "synthetic-management-token" not in output
    assert os.listdir(tmp_path / ".config" / "sauri" / "secrets") == []
