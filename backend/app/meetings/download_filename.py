"""File names for the recording download link (mirrors the portal's title-to-filename rules)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

MAX_BASE_LENGTH = 120
GENERIC_EXTENSION = "bin"

# Characters invalid on Windows, macOS or Linux file systems, plus control characters.
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f-\x9f]')
_MEDIA_EXTENSION = re.compile(r"\.(webm|mp4|m4a|mp3|wav|mov|mkv|ogg|opus)$", re.IGNORECASE)
_RESERVED_WINDOWS_NAME = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_EDGE_NOISE = re.compile(r"^[\s.]+|[\s.]+$")

_EXTENSION_BY_MIME = {
    "video/webm": "webm", "video/mp4": "mp4", "video/quicktime": "mov", "video/x-matroska": "mkv",
    "audio/webm": "webm", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/wave": "wav", "audio/ogg": "ogg", "audio/opus": "opus",
}  # fmt: skip


def media_extension(mime_type: str | None, object_ref: str) -> str:
    """Extension from the mime type, else from the stored object's name, else a generic one."""
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime in _EXTENSION_BY_MIME:
        return _EXTENSION_BY_MIME[mime]
    suffix = PurePosixPath(object_ref).suffix.lstrip(".").lower()
    if re.fullmatch(r"[a-z0-9]{2,5}", suffix):
        return suffix
    return GENERIC_EXTENSION


def media_filename(
    title: str | None, meeting_id: str, mime_type: str | None, object_ref: str
) -> str:
    """``<title>.<ext>`` with a title that is safe on every file system; id-based when unusable."""
    extension = media_extension(mime_type, object_ref)
    base = _clean_title(title)
    return f"{base or f'recording-{meeting_id}'}.{extension}"


def _clean_title(title: str | None) -> str | None:
    if not title:
        return None
    spaced = " ".join(_INVALID_CHARS.sub(" ", unicodedata.normalize("NFC", title)).split())
    base = _EDGE_NOISE.sub("", _MEDIA_EXTENSION.sub("", spaced))
    base = _EDGE_NOISE.sub("", base[:MAX_BASE_LENGTH])  # slicing a str never splits a code point
    if not base:
        return None
    if _RESERVED_WINDOWS_NAME.match(base.split(".")[0].strip()):
        base = f"_{base}"
    return base
