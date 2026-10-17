"""RED contract tests for authenticated, owner-scoped playback manifests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SessionRecording

OWNER_ID = "playback-owner"
OTHER_USER_ID = "playback-other"


def _auth_header(user_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Playback Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _meeting_with_recording(api_db_url: str, *, owner_id: str = OWNER_ID) -> str:
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
                created_by=owner_id,
                created_at=now,
            )
        )
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


@pytest.mark.asyncio
async def test_playback_manifest_requires_authentication(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from app.meetings import router

    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    response = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}/playback")
    assert response.status_code == 401
    assert "audio_source" not in response.text
    assert "private/" not in response.text
    assert store.signed == []


@pytest.mark.asyncio
async def test_non_owner_cannot_receive_manifest_or_private_references(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    from app.meetings import router

    meeting_id = await _meeting_with_recording(api_db_url)
    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header(OTHER_USER_ID)
    )
    assert response.status_code == 404
    assert "private/test/audio.webm" not in response.text
    assert "audio_source" not in response.text
    assert store.signed == []


@pytest.mark.asyncio
async def test_missing_and_non_owned_meetings_are_indistinguishable(
    api_client: AsyncClient, api_db_url: str
):
    owned_id = await _meeting_with_recording(api_db_url)
    missing_id = str(uuid.uuid4())
    responses = [
        await api_client.get(
            f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header(OTHER_USER_ID)
        )
        for meeting_id in (owned_id, missing_id)
    ]
    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert all("private/test/audio.webm" not in response.text for response in responses)


@pytest.mark.asyncio
async def test_owner_manifest_contains_only_signed_playback_contract(
    api_client: AsyncClient, api_db_url: str
):
    meeting_id = await _meeting_with_recording(api_db_url)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == meeting_id
    assert body["duration_seconds"] == 45
    assert body["audio_source"]["url"].startswith(("http://", "https://"))
    assert body["audio_source"]["source_id"]
    assert body["video_sources"] == []
    assert "private/test/audio.webm" not in response.text
    assert "audio_ref" not in body
    assert "object_ref" not in body


@pytest.mark.asyncio
async def test_invalid_token_cannot_receive_manifest(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from app.meetings import router

    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    response = await api_client.get(
        f"/api/v1/meetings/{uuid.uuid4()}/playback",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert "private/" not in response.text
    assert store.signed == []


async def _meeting_and_recording(api_db_url: str) -> tuple[str, str]:
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    meeting_id = str(uuid.uuid4())
    recording_id = str(uuid.uuid4())
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
            )
        )
        session.add(
            SessionRecording(
                id=recording_id,
                meeting_id=meeting_id,
                idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension",
                audio_ref="private/synthetic/audio.webm",
                video_ref=None,
                duration_seconds=45,
                interrupted=False,
                expires_at=None,
                finished_at=now,
            )
        )
    await engine.dispose()
    return meeting_id, recording_id


class _SyntheticObjectStore:
    def __init__(self):
        self.signed: list[tuple[str, int]] = []

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        self.signed.append((reference, ttl_seconds))
        return f"https://media.example.test/signed/{len(self.signed)}"


def _synthetic_inventory(*, video_presence: str, audio_source=None, video_sources=()):
    from types import SimpleNamespace

    return SimpleNamespace(
        video_presence=video_presence,
        audio_source=audio_source,
        video_sources=list(video_sources),
    )


def _source(source_id: str, object_ref: str, *, mime_type="video/webm", offset=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=source_id,
        object_ref=object_ref,
        mime_type=mime_type,
        quality_label="Original",
        width=None,
        height=None,
        video_offset_ms=offset,
    )


@pytest.mark.asyncio
async def test_no_recording_or_playable_audio_source_returns_no_playback_manifest(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    meeting_id = await _meeting_with_recording(api_db_url)
    from app.meetings import service

    async def no_audio(session, recording_id):
        return _synthetic_inventory(video_presence="absent", audio_source=None)

    monkeypatch.setattr(service, "load_playback_source_inventory", no_audio, raising=False)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 404
    assert "private/" not in response.text


@pytest.mark.asyncio
async def test_meeting_without_recording_has_no_playback_manifest(
    api_client: AsyncClient, api_db_url: str
):
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    meeting_id = str(uuid.uuid4())
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
                created_at=datetime.now(UTC),
            )
        )
    await engine.dispose()
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 404
    assert "private/" not in response.text


@pytest.mark.asyncio
async def test_explicit_muxed_evidence_returns_muxed_video_source(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    from app.meetings import router, service

    meeting_id, _ = await _meeting_and_recording(api_db_url)
    audio = _source("muxed-id", "private/synthetic/muxed.webm", mime_type="video/webm")

    async def inventory(session, recording_id):
        return _synthetic_inventory(video_presence="muxed", audio_source=audio)

    monkeypatch.setattr(service, "load_playback_source_inventory", inventory, raising=False)
    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store, raising=False)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["muxed_video_source"]["source_id"] == "muxed-id"
    assert body["muxed_video_source"]["mime_type"] == "video/webm"
    assert body["video_sources"] == []
    assert store.signed == [("private/synthetic/muxed.webm", 3600)]
    assert "private/" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("video_presence", "mime_type", "video_ref"),
    [("unknown", "video/webm", "private/legacy/video.webm"),
     ("unknown", None, "private/legacy/video.webm"),
     ("unknown", "video/webm", None)],
)
async def test_legacy_unknown_video_evidence_is_audio_only(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch,
    video_presence: str, mime_type: str | None, video_ref: str | None,
):
    from app.meetings import service

    meeting_id, _ = await _meeting_and_recording(api_db_url)
    audio = _source("audio-id", "private/synthetic/audio.webm", mime_type=mime_type)
    videos = [] if video_ref is None else [
        _source("legacy-video", video_ref, mime_type=mime_type, offset=None)
    ]

    async def inventory(session, recording_id):
        return _synthetic_inventory(
            video_presence=video_presence, audio_source=audio, video_sources=videos
        )

    monkeypatch.setattr(service, "load_playback_source_inventory", inventory, raising=False)
    store = _SyntheticObjectStore()
    from app.meetings import router
    monkeypatch.setattr(router, "_get_object_store", lambda: store, raising=False)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json()["video_sources"] == []
    assert all(reference == "private/synthetic/audio.webm" for reference, _ in store.signed)
    assert "private/" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("video_presence", ["absent", "unknown"])
async def test_only_explicit_muxed_evidence_selects_muxed_container(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch,
    video_presence: str,
):
    from app.meetings import router, service

    meeting_id, _ = await _meeting_and_recording(api_db_url)
    audio = _source("audio-id", "private/synthetic/muxed.webm", mime_type="video/webm")

    async def inventory(session, recording_id):
        return _synthetic_inventory(video_presence=video_presence, audio_source=audio)

    monkeypatch.setattr(service, "load_playback_source_inventory", inventory, raising=False)
    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store, raising=False)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("muxed_video_source") is None
    assert body["video_sources"] == []
    assert all("private/" not in value for value in response.text.split())


@pytest.mark.asyncio
async def test_separate_video_choices_include_only_known_signed_offsets_and_sign_with_ttl_3600(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    from app.meetings import router, service

    meeting_id, _ = await _meeting_and_recording(api_db_url)
    audio = _source("audio-id", "private/synthetic/audio.opus", mime_type="audio/ogg")
    videos = [
        _source("positive", "private/synthetic/video-positive.webm", offset=250),
        _source("negative", "private/synthetic/video-negative.webm", offset=-125),
        _source("legacy", "private/synthetic/video-unknown.webm", offset=None),
    ]

    async def inventory(session, recording_id):
        return _synthetic_inventory(
            video_presence="separate", audio_source=audio, video_sources=videos
        )

    monkeypatch.setattr(service, "load_playback_source_inventory", inventory, raising=False)
    store = _SyntheticObjectStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store, raising=False)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert [source["source_id"] for source in body["video_sources"]] == ["positive", "negative"]
    assert [source["video_offset_ms"] for source in body["video_sources"]] == [250, -125]
    assert len(body["video_sources"]) == 2
    assert store.signed == [
        ("private/synthetic/audio.opus", 3600),
        ("private/synthetic/video-positive.webm", 3600),
        ("private/synthetic/video-negative.webm", 3600),
    ]
    assert "private/" not in response.text
