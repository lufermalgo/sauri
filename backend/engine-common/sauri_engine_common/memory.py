"""Physical memory of this computer and the low-memory mode it implies (read-only, no network).

A Mac with less than 16 GiB (the 8 GB models) cannot keep the summary model loaded next to the browser, the
meeting app and the other engines without swapping, so the engines there free their models as soon as they are
done. ``SAURI_LOW_MEMORY`` (``1``/``0``) forces the mode either way; without it the mode follows the memory.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Final

SYSCTL: Final = "/usr/sbin/sysctl"
GIB: Final = 1024**3
# Below this much memory the low-memory mode applies; 16 GiB and up keep the normal behavior (the 9B needs 16).
LOW_MEMORY_BELOW_GIB: Final = 16
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


def is_low_memory(memory_gib: float) -> bool:
    """True for a known memory below 16 GiB; an unknown memory (0) keeps the normal behavior."""
    return 0 < memory_gib < LOW_MEMORY_BELOW_GIB


def low_memory_mode() -> bool:
    """Whether this computer runs in low-memory mode: ``SAURI_LOW_MEMORY`` when set, else its memory."""
    forced = os.getenv("SAURI_LOW_MEMORY", "").strip().lower()
    if forced in ("1", "true", "on"):
        return True
    if forced in ("0", "false", "off"):
        return False
    return is_low_memory(memory_bytes() / GIB)
