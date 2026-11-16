"""Helper programs never outlive their job (#1166)."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from sauri_engine_common import cancellation, process_group


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_run_captures_output_like_subprocess_run():
    done = process_group.run(["sh", "-c", "echo out; echo err >&2"], timeout=10, text=True)
    assert (done.returncode, done.stdout, done.stderr) == (0, "out\n", "err\n")


def test_a_failing_helper_raises_with_its_exit_code_and_stderr():
    with pytest.raises(subprocess.CalledProcessError) as error:
        process_group.run(["sh", "-c", "echo private >&2; exit 3"], timeout=10)
    assert error.value.returncode == 3 and error.value.stderr == b"private\n"


def test_the_time_limit_kills_the_helper_and_its_children(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        process_group.run(["sh", "-c", f"sleep 60 & echo $! > {pid_file}; wait"], timeout=1)
    assert time.monotonic() - started < 10
    assert wait_dead(int(pid_file.read_text()))


def test_a_caller_that_leaves_kills_the_whole_group_at_once(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    left = threading.Event()
    token = cancellation.bind(left)
    threading.Timer(1.0, left.set).start()
    try:
        started = time.monotonic()
        with pytest.raises(cancellation.JobCancelled):
            process_group.run(["sh", "-c", f"sleep 60 & echo $! > {pid_file}; wait"], timeout=120)
        assert time.monotonic() - started < 10
    finally:
        cancellation.unbind(token)
    assert wait_dead(int(pid_file.read_text()))
    assert not process_group._live


def test_shutdown_kills_every_helper_still_running(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    outcome: list[BaseException] = []

    def job() -> None:
        try:
            process_group.run(["sh", "-c", f"sleep 60 & echo $! > {pid_file}; wait"], timeout=120)
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            outcome.append(exc)

    thread = threading.Thread(target=job)
    thread.start()
    while not pid_file.exists() or not pid_file.read_text().strip():
        time.sleep(0.05)
    process_group.kill_all()
    thread.join(10)
    assert not thread.is_alive()
    assert wait_dead(int(pid_file.read_text()))
