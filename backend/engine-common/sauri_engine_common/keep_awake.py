"""Prevent idle sleep only while a native engine is working."""

from __future__ import annotations

import os
import subprocess
import sys
from types import TracebackType


class KeepAwakeError(RuntimeError):
    """The operating system could not start the idle-sleep inhibitor."""


class KeepAwake:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> KeepAwake:
        if sys.platform == "darwin":
            try:
                self.process = subprocess.Popen(
                    ["caffeinate", "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise KeepAwakeError("keep_awake_failed") from exc
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
