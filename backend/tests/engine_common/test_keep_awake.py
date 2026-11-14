"""Verify the actual sleep inhibitor is reaped on success and failure."""

import os
import sys

import pytest
from sauri_engine_common.keep_awake import KeepAwake


@pytest.mark.skipif(sys.platform != "darwin", reason="caffeinate is macOS-only")
@pytest.mark.parametrize("fail", [False, True])
def test_caffeinate_is_reaped(fail: bool) -> None:
    guard = KeepAwake()
    try:
        with guard:
            assert guard.process is not None
            assert guard.process.args == ["caffeinate", "-i", "-w", str(os.getpid())]
            pid = guard.process.pid
            os.kill(pid, 0)
            if fail:
                raise ValueError("synthetic failure")
    except ValueError:
        assert fail
    assert guard.process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_other_platforms_do_not_launch_caffeinate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with KeepAwake() as guard:
        assert guard.process is None
