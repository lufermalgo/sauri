"""Hardware detection for the local model recommendation (read-only, no network)."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from sauri_engine_common.memory import GIB, memory_bytes
from sauri_engine_common.recommend import HardwareProfile

__all__ = ["detect_hardware", "disk_free_bytes", "macos_major", "memory_bytes"]


def disk_free_bytes(path: Path) -> int:
    """Free bytes of the volume that holds ``path`` (or its nearest existing parent)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def macos_major() -> int:
    """Major version of macOS (``platform.mac_ver``); 0 elsewhere or when it cannot be read."""
    if platform.system() != "Darwin":
        return 0
    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return 0


def detect_hardware(models_dir: Path) -> HardwareProfile:
    arch, system = platform.machine(), platform.system()
    return HardwareProfile(
        arch=arch,
        memory_gib=round(memory_bytes() / GIB, 2),
        cores=os.cpu_count() or 1,
        # Metal acceleration is available on Apple silicon Macs only.
        metal=system == "Darwin" and arch == "arm64",
        disk_free_bytes=disk_free_bytes(models_dir),
        system=system,
        macos_major=macos_major(),
    )
