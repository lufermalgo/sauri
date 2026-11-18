"""Properties 3 and 4: atomic plain files and one shared confinement boundary."""

import asyncio
import io
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.infra.ensure_bucket import ensure_bucket
from app.infra.object_store import create_object_store
from app.infra.object_store_fs import FilesystemObjectStore

KEY = "recordings/meeting/recording/audio"
KEYS = st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=20),
                min_size=1, max_size=5).map("/".join)


@given(key=KEYS, content=st.binary(max_size=20000))
async def test_property_3_round_trip(key: str, content: bytes) -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = FilesystemObjectStore(Path(directory))
        assert await store.save(key, content) == key
        assert await store.get(key) == content
        stream = io.BytesIO(content)
        stream.seek(len(content))
        assert await store.save_stream(key, stream) == key
        assert await store.get(key) == content
        assert store.local_path(key).read_bytes() == content
        assert await store.inspect(key) == "available"
        await store.delete(key)
        await store.delete(key)
        assert await store.inspect(key) == "missing"
        assert not list(Path(directory).rglob("*.part"))


@given(content=st.binary(min_size=1, max_size=4096), existing=st.booleans())
async def test_property_3_interrupted_write_never_publishes_partial_bytes(content: bytes, existing: bool) -> None:
    class InterruptedStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            if self.tell():
                raise OSError("interrupted")
            return super().read(size)

    with tempfile.TemporaryDirectory() as directory:
        store = FilesystemObjectStore(Path(directory))
        if existing:
            await store.save(KEY, b"previous")
        with pytest.raises(OSError, match="interrupted"):
            await store.save_stream(KEY, InterruptedStream(content))
        if existing:
            assert await store.get(KEY) == b"previous"
        else:
            assert await store.inspect(KEY) == "missing"
        assert not list(Path(directory).rglob("*.part"))


@given(key=KEYS, kind=st.sampled_from(["absolute", "parent", "nul", "symlink", "sibling"]))
async def test_property_4_rejects_escapes_for_all_operations(key: str, kind: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "root"
        root.mkdir()
        outside = base / "root-sibling"
        outside.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        bad = {
            "absolute": str(outside / key), "parent": f"{key}/../audio",
            "nul": f"{key}\0", "symlink": f"link/{key}", "sibling": f"../root-sibling/{key}",
        }[kind]
        store = FilesystemObjectStore(root)
        with pytest.raises(ValueError, match="invalid_media_path"):
            store.local_path(bad)
        for operation in (store.save(bad, b"bad"), store.get(bad), store.delete(bad),
                          store.inspect(bad), store.get_bounded(bad, 10, time.monotonic() + 10),
                          store.temporary_read_url(bad)):
            with pytest.raises(ValueError, match="invalid_media_path"):
                await operation
        assert not list(outside.iterdir())


async def test_atomic_replace_and_fsync_failure_preserve_previous_file(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    await store.save(KEY, b"old")
    real_replace, real_fsync = os.replace, os.fsync
    events = []

    def fsync(fd):
        events.append("fsync")
        real_fsync(fd)

    def replace(source, destination):
        assert store.local_path(KEY).read_bytes() == b"old"
        assert Path(source).read_bytes() == b"new"
        assert events == ["fsync"]
        real_replace(source, destination)

    with patch("app.infra.object_store_fs.os.fsync", fsync), patch("app.infra.object_store_fs.os.replace", replace):
        await store.save(KEY, b"new")
    for target in ("fsync", "replace"):
        with (
            patch(f"app.infra.object_store_fs.os.{target}", side_effect=OSError("disk failure")),
            pytest.raises(OSError, match="disk failure"),
        ):
            await store.save(KEY, b"incomplete")
        assert await store.get(KEY) == b"new"
    assert not list(tmp_path.rglob("*.part"))


async def test_concurrent_writes_publish_only_complete_objects(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    values = [bytes([i]) * 100000 for i in range(10)]
    await asyncio.gather(*(store.save(KEY, content) for content in values))
    assert await store.get(KEY) in values
    assert not list(tmp_path.rglob("*.part"))


async def test_bounded_reads_enforce_size_and_deadline(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    await store.save(KEY, b"1234")
    assert await store.get_bounded(KEY, 4, time.monotonic() + 10) == b"1234"
    with pytest.raises(OSError):
        await store.get_bounded(KEY, 3, time.monotonic() + 10)
    with pytest.raises(ValueError):
        await store.get_bounded(KEY, 4, time.monotonic() - 1)
    with pytest.raises(ValueError):
        await store.get_bounded(KEY, -1, time.monotonic() + 10)
    await store.save(KEY, b"")
    assert await store.get_bounded(KEY, 0, time.monotonic() + 10) == b""


def test_factory_and_ensure_root_do_not_initialize_s3(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OBJECT_STORE_KIND", "filesystem")
    monkeypatch.setenv("SAURI_RECORDINGS_DIR", str(tmp_path / "recordings"))
    with patch("boto3.client", side_effect=AssertionError("S3 must not be initialized")):
        ensure_bucket()
        ensure_bucket()
        store = create_object_store()
    assert isinstance(store, FilesystemObjectStore)
    assert store.root.is_dir()


def test_factory_defaults_to_s3(monkeypatch) -> None:
    monkeypatch.delenv("OBJECT_STORE_KIND", raising=False)
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://storage.invalid")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test")
    with patch("app.infra.secrets.object_store_credentials", return_value=("test", "test")), \
            patch("app.infra.object_store_s3.S3ObjectStore") as constructor:
        assert create_object_store() is constructor.return_value
    constructor.assert_called_once()


async def test_cancelled_writer_is_reaped_without_publishing_or_leaving_parts(tmp_path: Path) -> None:
    import threading

    entered, release = threading.Event(), threading.Event()

    class PausedStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test writer did not resume")
            return super().read(size)

    store = FilesystemObjectStore(tmp_path)
    stream = PausedStream(b"new data")
    task = asyncio.create_task(store.save_stream(KEY, stream))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await store.inspect(KEY) == "missing"
    assert not list(tmp_path.rglob("*.part"))


async def test_save_stream_reads_large_upload_in_bounded_chunks(tmp_path: Path) -> None:
    reads = []

    class ChunkedStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    content = b"x" * (2 * 1024 * 1024 + 1)
    store = FilesystemObjectStore(tmp_path)
    await store.save_stream(KEY, ChunkedStream(content))
    assert await store.get(KEY) == content
    assert len(reads) == 4
