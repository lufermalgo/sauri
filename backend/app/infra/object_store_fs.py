"""Plain-file object store with atomic publication and signed API read URLs."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from app.infra.object_store import ObjectAvailability, ObjectStore
from app.ingestion.upload_limits import detect_container
from app.media.tokens import sign_media_token

# Like engines/routing.py, support the API source layout without installing the engines.
_COMMON = Path(__file__).resolve().parents[2] / "engine-common"
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.append(str(_COMMON))

from sauri_engine_common.local_media import local_media_path  # noqa: E402


class FilesystemObjectStore(ObjectStore):
    """Media MIME comes from the bytes, so copied recordings need no metadata sidecars."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def local_path(self, key: str) -> Path:
        return local_media_path(self.root, key)

    async def save(
        self, key: str, content: bytes, content_type: str = "application/octet-stream",
    ) -> str:
        return await self.save_stream(key, io.BytesIO(content), content_type)

    def _save_stream(self, key: str, content: BinaryIO, cancelled: threading.Event) -> None:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = self.local_path(key)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", suffix=".part", delete=False,
            ) as output:
                temporary = Path(output.name)
                content.seek(0)
                shutil.copyfileobj(content, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
                if cancelled.is_set():
                    return
                os.replace(temporary, self.local_path(key))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def save_stream(
        self, key: str, content: BinaryIO, content_type: str = "application/octet-stream",
    ) -> str:
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(self._save_stream, key, content, cancelled))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            # Do not let the caller close the upload while the writer still owns it.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            with suppress(BaseException):
                task.result()
            raise
        return key

    async def get(self, reference: str) -> bytes:
        return await asyncio.to_thread(self.local_path(reference).read_bytes)

    async def inspect(self, reference: str) -> ObjectAvailability:
        path = self.local_path(reference)
        try:
            await asyncio.to_thread(path.stat)
        except FileNotFoundError:
            return "missing"
        if not path.is_file():
            raise OSError("Object is not a regular file")
        return "available"

    async def delete(self, reference: str) -> None:
        await asyncio.to_thread(self.local_path(reference).unlink, missing_ok=True)

    async def get_bounded(self, reference: str, max_bytes: int, deadline_monotonic: float) -> bytes:
        if max_bytes < 0 or deadline_monotonic <= time.monotonic():
            raise ValueError("bounded object read unavailable")

        def read() -> bytes:
            with self.local_path(reference).open("rb") as source:
                if os.fstat(source.fileno()).st_size > max_bytes:
                    raise OSError("bounded object read unavailable")
                data = source.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise OSError("bounded object read unavailable")
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError("bounded object read deadline expired")
            return data

        async with asyncio.timeout(deadline_monotonic - time.monotonic()):
            return await asyncio.to_thread(read)

    def _content_type(self, reference: str) -> str:
        path = self.local_path(reference)
        # Keys have no extension; derive MIME from the same container signatures as ingestion.
        with path.open("rb") as source:
            header = source.read(16)
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        container = detect_container(header)
        if container is not None:
            return container.video_type if path.name == "video" else container.audio_type
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    async def _url(self, reference: str, ttl_seconds: int, filename: str | None = None) -> str:
        content_type = await asyncio.to_thread(self._content_type, reference)
        token = sign_media_token(reference, ttl_seconds, content_type, filename=filename)
        origin = os.environ.get("SAURI_PUBLIC_API_ORIGIN", "http://localhost:8000").rstrip("/")
        return f"{origin}/api/v1/media/{token}"

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        return await self._url(reference, ttl_seconds)

    async def temporary_download_url(self, reference: str, filename: str, ttl_seconds: int = 300) -> str:
        return await self._url(reference, ttl_seconds, filename)
