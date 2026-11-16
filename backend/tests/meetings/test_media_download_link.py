"""Owner-scoped, attachment-forcing download link for a recording's video (or audio)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import boto3
import pytest
from botocore.config import Config
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra import object_store_s3
from app.infra.models import Meeting, SessionRecording
from app.meetings.download_filename import media_extension, media_filename
from app.meetings.signed_urls import download_url_ttl_seconds

OWNER_ID = "download-owner"
OTHER_USER_ID = "download-other"


def _auth_header(user_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Download Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _meeting(api_db_url: str, *, title: str | None, with_recording: bool = True) -> str:
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    meeting_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=OWNER_ID,
                created_at=now,
                title=title,
            )
        )
        if with_recording:
            session.add(
                SessionRecording(
                    id=str(uuid.uuid4()),
                    meeting_id=meeting_id,
                    idempotency_key=str(uuid.uuid4()),
                    capture_origin="chrome_extension",
                    audio_ref="private/test/audio.webm",
                    video_ref=None,
                    duration_seconds=45,
                    interrupted=False,
                    expires_at=None,
                    finished_at=now,
                )
            )
    await engine.dispose()
    return meeting_id


class _Store:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, str, int]] = []
        self.reads: list[str] = []

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        self.reads.append(reference)
        return "https://media.example.test/playback"

    async def temporary_download_url(
        self, reference: str, filename: str, ttl_seconds: int = 300
    ) -> str:
        self.downloads.append((reference, filename, ttl_seconds))
        return f"https://media.example.test/download/{len(self.downloads)}"


def _source(object_ref: str, mime_type: str | None, offset: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=object_ref, object_ref=object_ref, mime_type=mime_type, video_offset_ms=offset
    )


def _inventory(monkeypatch: pytest.MonkeyPatch, presence: str, audio: Any, videos: Any = ()) -> None:
    from app.meetings import service

    async def inventory(session: AsyncSession, recording_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            video_presence=presence,
            duration_seconds=45,
            audio_source=audio,
            video_sources=list(videos),
        )

    monkeypatch.setattr(service, "load_playback_source_inventory", inventory)


def _store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    from app.meetings import router

    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    return store


def _url(meeting_id: str) -> str:
    return f"/api/v1/meetings/{meeting_id}/media-download"


@pytest.mark.asyncio
async def test_requires_authentication(api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(monkeypatch)
    response = await api_client.get(_url(str(uuid.uuid4())))
    assert response.status_code == 401
    assert store.downloads == []


@pytest.mark.asyncio
async def test_non_owner_and_missing_meetings_are_indistinguishable(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Weekly sync")
    responses = [
        await api_client.get(_url(identifier), headers=_auth_header(OTHER_USER_ID))
        for identifier in (meeting_id, str(uuid.uuid4()))
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert "private/" not in responses[0].text
    assert store.downloads == []


@pytest.mark.asyncio
async def test_meeting_without_recording_has_no_download(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Empty", with_recording=False)
    response = await api_client.get(_url(meeting_id), headers=_auth_header())
    assert response.status_code == 404
    assert store.downloads == []


@pytest.mark.asyncio
async def test_owner_gets_a_short_lived_attachment_link_named_after_the_title(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Caf\u00e9: plan Q3 / sales")
    _inventory(monkeypatch, "muxed", _source("private/test/muxed.webm", "video/webm"))
    response = await api_client.get(_url(meeting_id), headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "url": "https://media.example.test/download/1",
        "filename": "Caf\u00e9 plan Q3 sales.webm",
        "expires_in_seconds": 300,
    }
    assert store.downloads == [("private/test/muxed.webm", "Caf\u00e9 plan Q3 sales.webm", 300)]
    assert store.reads == []
    assert "private/" not in response.text


@pytest.mark.asyncio
async def test_download_link_lifetime_follows_the_environment(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Sync")
    monkeypatch.setenv("DOWNLOAD_URL_TTL_SECONDS", "120")
    monkeypatch.setenv("PLAYBACK_URL_TTL_SECONDS", "9000")
    response = await api_client.get(_url(meeting_id), headers=_auth_header())
    assert response.json()["expires_in_seconds"] == 120
    assert store.downloads[0][2] == 120


@pytest.mark.parametrize("raw", ["59", "3601", "abc"])
def test_download_ttl_rejects_out_of_range_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("DOWNLOAD_URL_TTL_SECONDS", raw)
    with pytest.raises(ValueError):
        download_url_ttl_seconds()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("presence", "expected_ref", "expected_name"),
    [
        ("absent", "private/test/audio.m4a", "Sync.m4a"),
        ("unknown", "private/test/audio.m4a", "Sync.m4a"),
        ("separate", "private/test/video-a.mp4", "Sync.mp4"),
    ],
)
async def test_source_choice_matches_the_player(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch,
    presence: str, expected_ref: str, expected_name: str,
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Sync")
    _inventory(
        monkeypatch, presence, _source("private/test/audio.m4a", "audio/mp4"),
        [_source("private/test/video-legacy.mp4", "video/mp4", None),
         _source("private/test/video-a.mp4", "video/mp4", 120),
         _source("private/test/video-b.mp4", "video/mp4", -5)],
    )
    response = await api_client.get(_url(meeting_id), headers=_auth_header())
    assert response.status_code == 200
    assert store.downloads == [(expected_ref, expected_name, 300)]


@pytest.mark.asyncio
async def test_separate_video_without_an_aligned_source_has_no_download(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(monkeypatch)
    meeting_id = await _meeting(api_db_url, title="Sync")
    _inventory(
        monkeypatch, "separate", _source("private/test/audio.m4a", "audio/mp4"),
        [_source("private/test/video.mp4", "video/mp4", None)],
    )
    response = await api_client.get(_url(meeting_id), headers=_auth_header())
    assert response.status_code == 404
    assert store.downloads == []


@pytest.mark.parametrize(
    ("title", "mime", "ref", "expected"),
    [
        ("Weekly sync", "video/webm", "a/b.webm", "Weekly sync.webm"),
        ("recording.webm", "video/webm", "a/b.webm", "recording.webm"),
        ("  ..Plan: Q3?*  ", "video/mp4", "a/b", "Plan Q3.mp4"),
        ("???", "audio/mp4", "a/b", "recording-m1.m4a"),
        (None, "audio/mpeg", "a/b", "recording-m1.mp3"),
        ("CON", "video/webm", "a/b", "_CON.webm"),
        ("x" * 300, "video/webm", "a/b", "x" * 120 + ".webm"),
        ("Line\u00ed\r\nnew\x00", "video/webm", "a/b", "Line\u00ed new.webm"),
        ("Clip", None, "private/x/file.MKV", "Clip.mkv"),
        ("Clip", "application/x-weird", "private/x/file", "Clip.bin"),
    ],
)
def test_media_filename(title: str | None, mime: str | None, ref: str, expected: str) -> None:
    assert media_filename(title, "m1", mime, ref) == expected


def test_media_extension_ignores_mime_parameters() -> None:
    assert media_extension("video/webm; codecs=vp9", "a/b") == "webm"


@pytest.mark.asyncio
async def test_s3_store_signs_response_content_disposition(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Client:
        def generate_presigned_url(self, **kwargs: Any) -> str:
            calls.append(kwargs)
            return "http://localhost:9000/bucket/key?signature=synthetic"

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: _Client())
    store = object_store_s3.S3ObjectStore(
        endpoint_url="http://minio:9000", bucket="bucket", access_key="a", secret_key="b"
    )
    await store.temporary_download_url("private/key.webm", "Caf\u00e9 ni\u00f1o.webm", ttl_seconds=120)

    assert calls[0]["ClientMethod"] == "get_object"
    assert calls[0]["ExpiresIn"] == 120
    params = calls[0]["Params"]
    assert params["Key"] == "private/key.webm"
    assert params["ResponseContentDisposition"] == (
        'attachment; filename="Cafe nino.webm"; '
        "filename*=UTF-8''Caf%C3%A9%20ni%C3%B1o.webm"
    )


@pytest.mark.parametrize("hostile", ['a"b; x=y.webm', "a\\b%2F.webm", "x\r\nSet-Cookie: a.webm"])
def test_content_disposition_never_breaks_out_of_the_quoted_name(hostile: str) -> None:
    header = object_store_s3.attachment_content_disposition(hostile)
    fallback = header.split('filename="', 1)[1].split('"; filename*=', 1)[0]
    assert '"' not in fallback and "\\" not in fallback and "%" not in fallback
    assert "\r" not in header and "\n" not in header
    assert unquote(header.split("UTF-8''", 1)[1]) == hostile


def test_real_botocore_signature_carries_the_disposition_in_the_query() -> None:
    client = boto3.client(
        "s3", endpoint_url="http://localhost:9000", region_name="us-east-1",
        aws_access_key_id="a", aws_secret_access_key="b", config=Config(signature_version="s3v4"),
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": "b", "Key": "k.webm",
            "ResponseContentDisposition": object_store_s3.attachment_content_disposition("\u00d1.webm"),
        },
        ExpiresIn=300,
    )
    query = parse_qs(urlparse(url).query)
    assert query["response-content-disposition"][0].startswith("attachment; filename=")
    assert query["X-Amz-Expires"] == ["300"]
