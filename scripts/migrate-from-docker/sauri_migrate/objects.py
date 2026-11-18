"""Copy recordings into the app's recordings folder and take the {key, size, MD5} inventory of both sides."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.infra.object_store_fs import FilesystemObjectStore

_MD5_HEX = re.compile(r"^[0-9a-f]{32}$")
CHUNK = 1024 * 1024


class ObjectCopyError(RuntimeError):
    """An object could not be copied exactly; the target keeps no partial file for it."""


@dataclass(frozen=True)
class ObjectRecord:
    key: str
    size: int
    md5: str


def etag_md5(etag: str) -> str | None:
    """The MD5 an S3 ETag carries for a single-part upload; None for multipart or unknown ETags."""
    value = etag.strip().strip('"').lower()
    return value if _MD5_HEX.match(value) else None


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def target_path(root: Path, key: str) -> Path:
    """The path the app itself reads for `key` (same confinement rules as FilesystemObjectStore)."""
    return FilesystemObjectStore(root).local_path(key)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_object(
    chunks: Iterable[bytes], root: Path, key: str, expected_size: int, expected_md5: str | None,
) -> tuple[ObjectRecord, bool]:
    """Write one object atomically; return its record and whether bytes were written.

    An existing file with the same size and MD5 is kept (re-running after an interruption); an existing
    file with different content is never overwritten.
    """
    path = target_path(root, key)
    if path.exists():
        if not path.is_file():
            raise ObjectCopyError(f"target is not a regular file: {key}")
        size = path.stat().st_size
        md5 = file_md5(path)
        if size == expected_size and (expected_md5 is None or md5 == expected_md5):
            return ObjectRecord(key, size, md5), False
        raise ObjectCopyError(f"a different file already exists in the target: {key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.md5(usedforsecurity=False)
    size = 0
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".part", delete=False,
        ) as output:
            temporary = Path(output.name)
            for chunk in chunks:
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        md5 = digest.hexdigest()
        if size != expected_size:
            raise ObjectCopyError(f"size differs for {key}: source {expected_size}, received {size}")
        if expected_md5 is not None and md5 != expected_md5:
            raise ObjectCopyError(f"MD5 differs from the ETag for {key}")
        os.replace(temporary, path)
        temporary = None
        _fsync_dir(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return ObjectRecord(key, size, md5), True


def scan_tree(root: Path) -> dict[str, ObjectRecord]:
    """Every object file under the recordings folder; hidden files (markers, partial writes) are skipped."""
    records: dict[str, ObjectRecord] = {}
    base = root.expanduser().resolve()
    if not base.is_dir():
        return records
    for directory, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            key = path.relative_to(base).as_posix()
            records[key] = ObjectRecord(key, path.stat().st_size, file_md5(path))
    return records
