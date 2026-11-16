"""`make build` and friends refuse to restart the stack while recordings are processing (#1166)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "scripts" / "platform" / "deploy-guard.sh"

# A stand-in for the docker CLI: what `compose ps` and the `psql` call print is set by the test.
STUB = """#!/usr/bin/env bash
case "$*" in
  *"ps --status running"*"rabbitmq"*) printf '%s' "${STUB_RABBIT_RUNNING:-}" ;;
  *"ps --status running"*) printf '%s' "${STUB_RUNNING:-}" ;;
  *"exec -T rabbitmq rabbitmqctl"*)
    if [[ -n "${STUB_RABBIT_ERROR:-}" ]]; then echo "${STUB_RABBIT_ERROR}" >&2; exit 2; fi
    printf '%s' "${STUB_QUEUES:-}"
    ;;
  *"exec -T postgres psql"*)
    if [[ -n "${STUB_PSQL_ERROR:-}" ]]; then echo "${STUB_PSQL_ERROR}" >&2; exit 2; fi
    printf '%s' "${STUB_ROWS:-}"
    ;;
  *) echo "unexpected docker call: $*" >&2; exit 99 ;;
esac
"""


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(STUB)
    docker.chmod(0o755)
    base = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "STUB_RUNNING": "postgres-container-id",
            "STUB_RABBIT_RUNNING": "rabbitmq-container-id"}
    return subprocess.run(
        ["bash", str(GUARD), "rebuild and recreate the API and worker"],
        env={**base, **env}, capture_output=True, text=True, check=False,
    )


def test_refuses_and_lists_what_is_in_flight(tmp_path: Path) -> None:
    rows = "meeting 6c6469e2 transcribing 2026-11-16 14:58\nsummary 11111111 running 2026-11-16 15:30\n"
    result = _run(tmp_path, STUB_ROWS=rows)

    assert result.returncode == 1
    assert "6c6469e2" in result.stderr and "11111111" in result.stderr
    assert "FORCE=1" in result.stderr and "rebuild and recreate the API and worker" in result.stderr


def test_passes_when_nothing_is_processing(tmp_path: Path) -> None:
    result = _run(tmp_path, STUB_ROWS="")
    assert result.returncode == 0 and result.stderr == ""


def test_passes_without_looking_when_the_database_is_not_running(tmp_path: Path) -> None:
    result = _run(tmp_path, STUB_RUNNING="", STUB_PSQL_ERROR="must not be called")
    assert result.returncode == 0


def test_force_skips_the_check_even_with_work_in_flight(tmp_path: Path) -> None:
    result = _run(tmp_path, FORCE="1", STUB_ROWS="meeting 6c6469e2 transcribing 2026-11-16 14:58\n")
    assert result.returncode == 0
    assert "FORCE=1" in result.stdout


def test_fails_closed_when_the_check_itself_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, STUB_PSQL_ERROR="psql: connection refused")
    assert result.returncode == 1
    assert "connection refused" in result.stderr and "FORCE=1" in result.stderr


@pytest.mark.parametrize("target", ["build", "up", "down", "clean", "engines-down"])
def test_every_make_target_that_restarts_something_runs_the_guard_first(target: str) -> None:
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]
    assert recipe.lstrip().startswith("bash scripts/platform/deploy-guard.sh")


def test_refuses_for_speakers_in_progress_and_for_live_claims_of_a_completed_meeting(tmp_path: Path) -> None:
    rows = "speakers f465e9b3 in_progress 2026-11-16 15:51\nlive-claim f465e9b3 diarization 2026-11-16 15:54\n"
    result = _run(tmp_path, STUB_ROWS=rows)

    assert result.returncode == 1
    assert "speakers f465e9b3 in_progress" in result.stderr and "live-claim f465e9b3 diarization" in result.stderr


def test_refuses_while_messages_wait_or_are_being_handled_in_a_processing_queue(tmp_path: Path) -> None:
    queues = "transcribe 0\ndiarize 1\nsummarize.defer 2\nother 7\n"
    result = _run(tmp_path, STUB_QUEUES=queues)

    assert result.returncode == 1
    assert "queue diarize 1 message(s)" in result.stderr and "queue summarize.defer 2 message(s)" in result.stderr
    assert "other" not in result.stderr and "queue transcribe" not in result.stderr


def test_passes_when_every_processing_queue_is_empty(tmp_path: Path) -> None:
    result = _run(tmp_path, STUB_QUEUES="transcribe 0\ndiarize 0\nsummarize 0\nsummarize.retry 0\n")
    assert result.returncode == 0


def test_fails_closed_when_the_broker_cannot_be_asked(tmp_path: Path) -> None:
    result = _run(tmp_path, STUB_RABBIT_ERROR="rabbitmqctl: node is down")
    assert result.returncode == 1 and "node is down" in result.stderr
