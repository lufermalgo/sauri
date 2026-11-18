"""Resolve recording keys without allowing access outside the configured root."""

from pathlib import Path


class InvalidMediaPathError(ValueError):
    """The reference is not a confined local object key."""


def local_media_path(root: Path, key: str) -> Path:
    if (
        not key or "\0" in key or "\\" in key or Path(key).is_absolute()
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise InvalidMediaPathError("invalid_media_path")
    try:
        base = root.expanduser().resolve()
        path = (base / key).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise InvalidMediaPathError("invalid_media_path") from exc
    if not path.is_relative_to(base) or path == base:
        raise InvalidMediaPathError("invalid_media_path")
    return path
