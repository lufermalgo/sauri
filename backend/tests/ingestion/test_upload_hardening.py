"""Upload cap, container verification, storage hygiene and error hygiene of the ingestion API."""

from __future__ import annotations

import json
import tracemalloc
import uuid
from collections.abc import AsyncIterator
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.schemas import AuthenticatedUser
from app.infra.models import Meeting
from app.ingestion import router as ingestion_router
from app.ingestion.upload_limits import (
    DEFAULT_MAX_UPLOAD_BYTES,
    MAX_CONFIGURABLE_UPLOAD_BYTES,
    detect_container,
    max_upload_bytes,
)
from app.main import app
from tests import media_samples

UPLOAD_URL = "/api/v1/ingestion/upload"
BOUNDARY = "sauri-test-boundary"
CHUNK = b"\x00" * 65536


class _CapturingStore:
    """Object store double that records what the router streams to it."""

    def __init__(self) -> None:
        self.saved: dict[str, tuple[bytes, str]] = {}

    async def save_stream(self, key: str, content: Any, content_type: str) -> str:
        content.seek(0)
        self.saved[key] = (content.read(), content_type)
        return f"stored/{key}"

    async def delete(self, _reference: str) -> None:
        return None


@pytest.fixture
def store() -> _CapturingStore:
    return _CapturingStore()


@pytest.fixture
def stack(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    store: _CapturingStore,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("APP_ENV", "test")
    queue = SimpleNamespace(connect=AsyncMock(), publish=AsyncMock(), disconnect=AsyncMock())
    monkeypatch.setattr(ingestion_router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(ingestion_router, "_get_queue", Mock(return_value=queue))
    monkeypatch.setattr(
        ingestion_router, "create_engine", Mock(return_value=SimpleNamespace(dispose=AsyncMock()))
    )
    monkeypatch.setattr(
        ingestion_router, "create_session_factory", Mock(return_value=session_factory)
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _data(**overrides: Any) -> str:
    payload = {
        "meeting_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "capture_origin": "web_upload",
        "duration_seconds": 3,
        "video_presence": "absent",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _multipart(
    data: str, audio: bytes, *, filename: str = "recording.webm", content_type: str = "audio/webm",
    video: bytes | None = None,
) -> bytes:
    def part(name: str, body: bytes, extra: str = "") -> bytes:
        return (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"{extra}\r\n"
            + (f"Content-Type: {content_type}\r\n" if extra else "")
            + "\r\n"
        ).encode() + body + b"\r\n"

    body = part("data", data.encode()) + part("audio", audio, f'; filename="{filename}"')
    if video is not None:
        body += part("video", video, '; filename="video.webm"')
    return body + f"--{BOUNDARY}--\r\n".encode()


_HEADERS = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}


# --- container detection -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sample", "name"),
    [
        (media_samples.WEBM, "webm"),
        (media_samples.MP4, "mp4"),
        (media_samples.MOV, "mp4"),
        (media_samples.MP3_ID3, "mp3"),
        (media_samples.MP3_FRAME, "mp3"),
        (media_samples.WAV, "wav"),
        (media_samples.OGG, "ogg"),
        (media_samples.FLAC, "flac"),
        (b"\xff\xf1\x50\x80" + b"\x00" * 12, "aac"),
    ],
)
def test_known_containers_are_recognised_from_their_first_bytes(sample: bytes, name: str) -> None:
    container = detect_container(sample)
    assert container is not None
    assert container.name == name


@pytest.mark.parametrize(
    "sample",
    [
        b"",
        b"<html><script>alert(1)</script>",
        b"MZ\x90\x00\x03\x00\x00\x00",
        b"%PDF-1.7\n",
        b"PK\x03\x04" + b"\x00" * 12,
        b"RIFF\x24\x00\x00\x00AVI LIST",  # RIFF but not WAVE
        b"\xff\xe9\x00\x00",  # reserved MPEG version
        b"synthetic-audio",
    ],
)
def test_other_content_is_not_a_media_container(sample: bytes) -> None:
    assert detect_container(sample) is None


def test_stored_content_type_ignores_a_type_that_does_not_match_the_container() -> None:
    container = detect_container(media_samples.WEBM)
    assert container is not None
    assert container.stored_content_type("text/html", video=False) == "audio/webm"
    assert container.stored_content_type("video/webm;codecs=vp9,opus", video=False) == "video/webm"
    assert container.stored_content_type(None, video=True) == "video/webm"
    assert container.stored_content_type("audio/mpeg", video=False) == "audio/webm"


# --- cap configuration -----------------------------------------------------------------------


def test_upload_cap_defaults_to_four_gibibytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    assert max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES == 4 * 1024**3


@pytest.mark.parametrize("value", ["0", "-1", "abc", str(MAX_CONFIGURABLE_UPLOAD_BYTES + 1)])
def test_invalid_upload_cap_is_rejected_instead_of_lifting_the_limit(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", value)
    with pytest.raises(ValueError):
        max_upload_bytes()


def test_upload_cap_accepts_a_configured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1048576")
    assert max_upload_bytes() == 1_048_576


# --- size cap over HTTP ------------------------------------------------------------------------


@pytest.mark.usefixtures("stack")
async def test_oversized_stream_is_cut_off_at_the_cap_without_buffering_it(
    client: AsyncClient, store: _CapturingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap = 2 * 1024 * 1024
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(cap))
    produced = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal produced
        yield (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"data\"\r\n\r\n{_data()}\r\n"
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"audio\"; "
            f"filename=\"a.webm\"\r\nContent-Type: audio/webm\r\n\r\n"
        ).encode() + media_samples.WEBM
        for _ in range(100_000):  # would be about 6 GB if nothing stopped it
            produced += len(CHUNK)
            yield CHUNK

    tracemalloc.start()
    try:
        response = await client.post(UPLOAD_URL, content=body(), headers=_HEADERS)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert response.status_code == 413
    assert response.json() == {"detail": "payload_too_large"}
    assert produced <= cap + 4 * len(CHUNK)  # the client was stopped near the cap
    assert peak < cap  # nothing close to the stream size was ever held in memory
    assert store.saved == {}


@pytest.mark.usefixtures("stack")
async def test_declared_content_length_over_the_cap_is_rejected_before_reading_the_body(
    client: AsyncClient, store: _CapturingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1048576")
    consumed = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed += 1
        yield b"x"

    response = await client.post(
        UPLOAD_URL, content=body(), headers={**_HEADERS, "content-length": str(10**12)}
    )

    assert response.status_code == 413
    assert consumed == 0
    assert store.saved == {}


@pytest.mark.usefixtures("stack")
async def test_a_part_just_under_the_cap_is_stored_intact(
    client: AsyncClient, store: _CapturingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1048576")
    audio = media_samples.WEBM + bytes(range(256)) * 2048  # 512 KiB, forces the disk spool

    response = await client.post(
        UPLOAD_URL, content=_multipart(_data(), audio), headers=_HEADERS
    )

    assert response.status_code == 200, response.text
    [(content, content_type)] = store.saved.values()
    assert content == audio
    assert content_type == "audio/webm"


class _VirtualFile:
    """A seekable file that claims a huge size without allocating any of it."""

    def __init__(self, size: int) -> None:
        self._size, self._position, self.reads = size, 0, 0

    def seek(self, offset: int, whence: int = 0) -> int:
        self._position = offset if whence == 0 else self._size + offset
        return self._position

    def tell(self) -> int:
        return self._position

    def read(self, count: int = -1) -> bytes:
        self.reads += 1
        return b""


async def test_handler_refuses_a_part_larger_than_the_cap_without_reading_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1048576")
    virtual = _VirtualFile(50 * 1024**3)
    monkeypatch.setattr(
        ingestion_router, "_get_object_store",
        Mock(side_effect=AssertionError("storage must not be reached")),
    )

    with pytest.raises(HTTPException) as error:
        await ingestion_router.upload_recording(
            audio=UploadFile(filename="huge.webm", file=virtual),  # type: ignore[arg-type]
            video=None,
            data=_data(),
            user=AuthenticatedUser(id="u", email="u@example.test", name="U", is_sales=True),
        )

    assert error.value.status_code == 413
    assert error.value.detail == "payload_too_large"
    assert virtual.reads == 0


# --- container verification over HTTP -------------------------------------------------------------


@pytest.mark.usefixtures("stack")
@pytest.mark.parametrize(
    "content",
    [b"<html>not media</html>", b"MZ\x90\x00", b"", b"%PDF-1.7"],
)
async def test_non_media_audio_part_is_415_even_with_an_audio_content_type(
    client: AsyncClient, store: _CapturingStore, content: bytes
) -> None:
    response = await client.post(
        UPLOAD_URL, content=_multipart(_data(), content, content_type="audio/webm"), headers=_HEADERS
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "unsupported_media_type"}
    assert store.saved == {}


@pytest.mark.usefixtures("stack")
async def test_non_media_video_part_is_415_and_nothing_is_stored(
    client: AsyncClient, store: _CapturingStore
) -> None:
    data = _data(video_presence="separate", video_offset_ms=0)
    response = await client.post(
        UPLOAD_URL,
        content=_multipart(data, media_samples.WEBM + b"a", video=b"not a video"),
        headers=_HEADERS,
    )

    assert response.status_code == 415
    assert store.saved == {}


@pytest.mark.usefixtures("stack")
async def test_client_file_name_and_type_never_reach_storage(
    client: AsyncClient,
    store: _CapturingStore,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = str(uuid.uuid4())
    response = await client.post(
        UPLOAD_URL,
        content=_multipart(
            _data(meeting_id=meeting_id),
            media_samples.WEBM + b"payload",
            filename="../../etc/passwd.webm",
            content_type="text/html",
        ),
        headers=_HEADERS,
    )

    assert response.status_code == 200, response.text
    [(key, (_, content_type))] = store.saved.items()
    assert key.startswith(f"recordings/{meeting_id}/")
    assert "passwd" not in key and ".." not in key
    assert content_type == "audio/webm"
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
    assert meeting is not None
    assert meeting.title == "passwd.webm"


# --- error hygiene ------------------------------------------------------------------------------


@pytest.mark.usefixtures("stack")
@pytest.mark.parametrize(
    "data",
    [
        "not-json{secret-token",
        "[]",
        json.dumps({"meeting_id": "m" * 37, "idempotency_key": "k", "capture_origin": "web_upload",
                    "duration_seconds": 1, "video_presence": "absent"}),
        json.dumps({"meeting_id": "ok", "idempotency_key": "k" * 257, "capture_origin": "web_upload",
                    "duration_seconds": 1, "video_presence": "absent"}),
        json.dumps({"meeting_id": "ok", "idempotency_key": "k", "capture_origin": "web_upload",
                    "duration_seconds": 1, "video_presence": "absent", "surprise-field": "x"}),
    ],
)
async def test_invalid_metadata_gives_a_generic_422_that_echoes_nothing(
    client: AsyncClient, store: _CapturingStore, data: str
) -> None:
    response = await client.post(
        UPLOAD_URL, content=_multipart(data, media_samples.WEBM), headers=_HEADERS
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    for fragment in ("secret-token", "surprise-field", "kkkk", "mmmm", "Expecting"):
        assert fragment not in response.text
    assert store.saved == {}


@pytest.mark.usefixtures("stack")
async def test_missing_part_422_lists_the_location_without_the_submitted_input(
    client: AsyncClient,
) -> None:
    body = (
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"data\"\r\n\r\n"
        f"{_data()}\r\n--{BOUNDARY}--\r\n"
    ).encode()

    response = await client.post(UPLOAD_URL, content=body, headers=_HEADERS)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "invalid_request",
        "errors": [{"loc": ["body", "audio"], "type": "missing"}],
    }


def test_ingestion_data_bounds() -> None:
    from pydantic import ValidationError

    from app.ingestion.schemas import IngestionData

    base: dict[str, Any] = {
        "meeting_id": "m-1", "idempotency_key": "k", "capture_origin": "web_upload",
        "duration_seconds": 1, "video_presence": "absent",
    }
    assert IngestionData(**base, title="t" * 512, meet_link="l" * 512).title == "t" * 512
    for bad in (
        {"title": "t" * 513},
        {"meet_link": "l" * 513},
        {"meeting_id": "m" * 37},
        {"meeting_id": "bad id"},
        {"meeting_id": "../x"},
        {"meeting_id": ""},
        {"idempotency_key": "k" * 257},
        {"idempotency_key": ""},
        {"duration_seconds": 604_801},
        {"duration_seconds": -1},
        {"notice_issued_at": "yesterday"},
        {"notice_issued_at": "2026-01-01T00:00:00Z" + "0" * 64},
        {"language": "english"},
        {"language": "E1"},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            IngestionData(**{**base, **bad})
    assert IngestionData(**base, notice_issued_at="2026-11-16T01:02:03.456Z")
    assert IngestionData(**base, language="auto").language == "auto"


async def test_direct_call_with_valid_media_still_streams_the_spooled_file(
    monkeypatch: pytest.MonkeyPatch, store: _CapturingStore,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(ingestion_router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(
        ingestion_router, "_get_queue",
        Mock(return_value=SimpleNamespace(connect=AsyncMock(), publish=AsyncMock(), disconnect=AsyncMock())),
    )
    monkeypatch.setattr(
        ingestion_router, "create_engine", Mock(return_value=SimpleNamespace(dispose=AsyncMock()))
    )
    monkeypatch.setattr(ingestion_router, "create_session_factory", Mock(return_value=session_factory))

    result = await ingestion_router.upload_recording(
        audio=UploadFile(filename="a.webm", file=BytesIO(media_samples.WEBM + b"abc")),
        video=None,
        data=_data(),
        user=AuthenticatedUser(id="u", email="u@example.test", name="U", is_sales=True),
    )

    assert result["state"] == "transcribing"
    [(content, _)] = store.saved.values()
    assert content == media_samples.WEBM + b"abc"
