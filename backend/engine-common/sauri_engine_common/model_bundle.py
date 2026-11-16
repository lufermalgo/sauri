"""A model made of several files (a CoreML bundle): pure helpers shared by the host service and the gateways.

The catalog lists every file with its size and SHA-256 and carries one digest of that listing as the model's
``sha256``, so a catalog edit cannot change a file without changing the digest. The manifest written after a
verified install records, per file, the size and ``mtime_ns``; nothing is hashed per request. A file replaced
after the install changes its ``mtime_ns`` and the bundle is refused until it is verified again.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

MAX_BUNDLE_FILES: Final = 64


@dataclass(frozen=True)
class BundleFile:
    path: str  # relative, POSIX separators, no ``..``
    size: int
    sha256: str


def bundle_digest(files: Sequence[BundleFile]) -> str:
    """SHA-256 of the sorted ``path NUL size NUL sha256 LF`` listing; the bundle's identity in the catalog."""
    listing = "".join(f"{f.path}\0{f.size}\0{f.sha256}\n" for f in sorted(files, key=lambda f: f.path))
    return hashlib.sha256(listing.encode()).hexdigest()


def bundle_size(files: Sequence[BundleFile]) -> int:
    return sum(f.size for f in files)


def snapshot(directory: Path, files: Sequence[BundleFile]) -> dict[str, dict[str, int]] | None:
    """Size and ``mtime_ns`` of every bundle file, or None when one is missing, not a regular file or the wrong size.

    ``lstat`` only: a symlink anywhere in the bundle (the directory included) makes it unusable.
    """
    try:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            return None
    except OSError:
        return None
    result: dict[str, dict[str, int]] = {}
    for item in files:
        try:
            info = (directory / item.path).lstat()
        except OSError:
            return None
        if not stat.S_ISREG(info.st_mode) or info.st_size != item.size:
            return None
        result[item.path] = {"size": info.st_size, "mtime_ns": info.st_mtime_ns}
    return result


def manifest_vouches(record: Mapping[str, Any] | None, found: Mapping[str, Mapping[str, int]], digest: str) -> bool:
    """The manifest says ``installed`` for this bundle digest and exactly these sizes and ``mtime_ns`` values."""
    return (
        record is not None
        and record.get("status") == "installed"
        and record.get("sha256") == digest
        and record.get("files") == {path: dict(values) for path, values in found.items()}
    )


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(directory: Path, files: Sequence[BundleFile]) -> str | None:
    """Hash every file; return the path of the first mismatch, or None when all match. Blocking."""
    for item in files:
        target = directory / item.path
        try:
            if target.lstat().st_size != item.size or file_digest(target) != item.sha256:
                return item.path
        except OSError:
            return item.path
    return None


def safe_relative(path: str) -> bool:
    parts = path.split("/")
    return (
        bool(path)
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in parts)
        and os.path.normpath(path) == path
    )
