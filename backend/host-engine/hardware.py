"""Hardware detection for the local model recommendation (read-only, no network)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Final

from sauri_engine_common.recommend import HardwareProfile

SYSCTL: Final = "/usr/sbin/sysctl"
_GIB: Final = 1024**3
_SYSCTL_TIMEOUT_S: Final = 2.0


def memory_bytes() -> int:
    """Total physical memory: ``sysctl hw.memsize`` on macOS, ``sysconf`` elsewhere; 0 when unknown."""
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                [SYSCTL, "-n", "hw.memsize"], capture_output=True, text=True, timeout=_SYSCTL_TIMEOUT_S, check=True
            )
            return int(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return 0


def disk_free_bytes(path: Path) -> int:
    """Free bytes of the volume that holds ``path`` (or its nearest existing parent)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def detect_hardware(models_dir: Path) -> HardwareProfile:
    arch, system = platform.machine(), platform.system()
    return HardwareProfile(
        arch=arch,
        memory_gib=round(memory_bytes() / _GIB, 2),
        cores=os.cpu_count() or 1,
        # Metal acceleration is available on Apple silicon Macs only.
        metal=system == "Darwin" and arch == "arm64",
        disk_free_bytes=disk_free_bytes(models_dir),
        system=system,
    )
