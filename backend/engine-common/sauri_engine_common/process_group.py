"""Run an engine's helper program (whisper-cli, the VAD tool) so that nothing outlives its job (#1166).

``run`` mirrors the parts of ``subprocess.run`` the engines use, but starts the child in its own
process group, polls while it waits, and kills the whole group when the job is cancelled (the caller
left), when the time runs out, or when the engine shuts down (``kill_all``). A child that kept running
after its parent stopped used to go on through the rest of a recording nobody was waiting for.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any

from sauri_engine_common import cancellation

POLL_S = 0.5

_live: dict[int, subprocess.Popen[Any]] = {}
_lock = threading.Lock()


def _kill(process: subprocess.Popen[Any]) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(Exception):
        process.communicate(timeout=5)  # reaps the child and drains its pipes


def kill_all() -> None:
    """Kill every helper still running (engine shutdown)."""
    with _lock:
        processes = list(_live.values())
    for process in processes:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)


def run(
    command: Sequence[str],
    *,
    timeout: float,
    check: bool = True,
    capture_output: bool = True,
    text: bool = False,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Like ``subprocess.run`` (same arguments, plus ``env``) but the child is killed on cancellation or timeout."""
    pipe = subprocess.PIPE if capture_output else None
    process = subprocess.Popen(command, stdout=pipe, stderr=pipe, text=text, start_new_session=True, env=env)
    with _lock:
        _live[process.pid] = process
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=max(min(POLL_S, deadline - time.monotonic()), 0.01))
                break
            except subprocess.TimeoutExpired:
                if cancellation.cancelled():
                    raise cancellation.JobCancelled from None
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout) from None
    except BaseException:
        _kill(process)
        raise
    finally:
        with _lock:
            _live.pop(process.pid, None)
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
