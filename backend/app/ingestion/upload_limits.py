"""Upload size cap and container verification for the ingestion endpoint.

Three independent defences, none of which trusts the client:

* ``Content-Length`` is checked before any body byte is read, and the body stream is
  counted while it is parsed, so a chunked or lying client is cut off at the cap.
  Starlette spools multipart file parts to disk (1 MB in memory), so an oversized
  request never grows process memory; the cap bounds the disk it can use.
* The container is identified from the first bytes of each file, never from the
  client-supplied ``Content-Type`` or file name.
* The stored ``Content-Type`` is derived from the detected container.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, BinaryIO

from fastapi import Request, Response

from app.infra.http_errors import (
    PAYLOAD_TOO_LARGE,
    UNSUPPORTED_MEDIA_TYPE,
    SafeErrorRoute,
    api_error,
)

GIB = 1024**3
DEFAULT_MAX_UPLOAD_BYTES = 4 * GIB
# One S3 PUT carries at most 5 GiB and the store adapter does not use multipart upload.
MAX_CONFIGURABLE_UPLOAD_BYTES = 5 * GIB
SNIFF_BYTES = 16


def max_upload_bytes() -> int:
    """Read ``MAX_UPLOAD_BYTES``: the cap on a whole upload request, in bytes.

    The default (4 GiB) covers the longest recording measured so far (94 min, 380 MB)
    more than tenfold. An unreadable value raises instead of silently lifting the cap.
    """
    raw = os.environ.get("MAX_UPLOAD_BYTES")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("MAX_UPLOAD_BYTES must be an integer") from exc
    if not 1 <= value <= MAX_CONFIGURABLE_UPLOAD_BYTES:
        raise ValueError(f"MAX_UPLOAD_BYTES must be between 1 and {MAX_CONFIGURABLE_UPLOAD_BYTES}")
    return value


@dataclass(frozen=True)
class MediaContainer:
    """A recognised container and the content types that may be stored for it."""

    name: str
    audio_type: str
    video_type: str
    accepted_client_types: frozenset[str]

    def stored_content_type(self, client_type: str | None, *, video: bool) -> str:
        """The client type only when it names this very container; otherwise the default."""
        base = (client_type or "").split(";", maxsplit=1)[0].strip().lower()
        if base in self.accepted_client_types:
            return base
        return self.video_type if video else self.audio_type


_WEBM = MediaContainer(
    "webm", "audio/webm", "video/webm",
    frozenset({"audio/webm", "video/webm", "audio/x-matroska", "video/x-matroska"}),
)
_MP4 = MediaContainer(
    "mp4", "audio/mp4", "video/mp4",
    frozenset({
        "audio/mp4", "video/mp4", "audio/x-m4a", "audio/m4a", "video/quicktime", "audio/aac",
    }),
)
_MP3 = MediaContainer("mp3", "audio/mpeg", "audio/mpeg", frozenset({"audio/mpeg", "audio/mp3"}))
_WAV = MediaContainer(
    "wav", "audio/wav", "audio/wav", frozenset({"audio/wav", "audio/x-wav", "audio/wave"})
)
_OGG = MediaContainer(
    "ogg", "audio/ogg", "video/ogg", frozenset({"audio/ogg", "video/ogg", "application/ogg"})
)
_FLAC = MediaContainer("flac", "audio/flac", "audio/flac", frozenset({"audio/flac", "audio/x-flac"}))
_AAC = MediaContainer("aac", "audio/aac", "audio/aac", frozenset({"audio/aac", "audio/x-aac"}))


def detect_container(header: bytes) -> MediaContainer | None:
    """Identify a media container from its first bytes; None when it is not one we accept."""
    if header.startswith(b"\x1a\x45\xdf\xa3"):  # EBML: WebM and Matroska
        return _WEBM
    if header[4:8] == b"ftyp":  # ISO base media: MP4, M4A, MOV (brand "qt  ")
        return _MP4
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return _WAV
    if header.startswith(b"OggS"):
        return _OGG
    if header.startswith(b"fLaC"):
        return _FLAC
    if header.startswith(b"ID3"):
        return _MP3
    if len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0:
        layer = (header[1] >> 1) & 0b11
        version = (header[1] >> 3) & 0b11
        if version != 0b01:  # 01 is reserved
            return _AAC if layer == 0 else _MP3  # layer 00 is an ADTS (AAC) frame
    return None


def sniff_container(file: BinaryIO) -> MediaContainer:
    """Read the leading bytes of a spooled upload and rewind it; 415 for anything else."""
    file.seek(0)
    header = file.read(SNIFF_BYTES)
    file.seek(0)
    container = detect_container(header)
    if container is None:
        raise api_error(415, UNSUPPORTED_MEDIA_TYPE)
    return container


def size_of(file: BinaryIO) -> int:
    """Size of a seekable upload without reading it."""
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size


class _CappedRequest(Request):
    """Request whose body stream fails with 413 as soon as it exceeds the cap."""

    def __init__(self, request: Request, cap: int) -> None:
        super().__init__(request.scope, request.receive)
        self._cap = cap

    async def stream(self) -> AsyncGenerator[bytes, None]:
        received = 0
        async for chunk in super().stream():
            received += len(chunk)
            if received > self._cap:
                raise api_error(413, PAYLOAD_TOO_LARGE)
            yield chunk


class CappedUploadRoute(SafeErrorRoute):
    """Route class that enforces ``MAX_UPLOAD_BYTES`` before the multipart body is parsed."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            cap = max_upload_bytes()
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > cap:
                raise api_error(413, PAYLOAD_TOO_LARGE)
            return await original(_CappedRequest(request, cap))

        return handler
