"""Compose contract tests for backend service startup ordering."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_worker_waits_for_rabbitmq_health_before_starting() -> None:
    """Prevent the worker from exiting on cold Compose startup before RabbitMQ is ready."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is required to validate the Compose startup contract")

    repository_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment.update(
        {
            "SPEAKER_EXCERPT_ACTIVE_KEY_ID": "qa-v1",
            "SPEAKER_EXCERPT_KEYRING": "qa-v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        }
    )
    compose_command = [
        docker,
        "compose",
        "-f",
        str(repository_root / "docker-compose.yml"),
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(
        compose_command,
        check=True,
        capture_output=True,
        text=True,
        cwd=repository_root,
        env=environment,
    )
    services = json.loads(result.stdout)["services"]

    assert services["rabbitmq"].get("healthcheck") is not None
    assert services["worker"]["depends_on"]["rabbitmq"]["condition"] == "service_healthy"
