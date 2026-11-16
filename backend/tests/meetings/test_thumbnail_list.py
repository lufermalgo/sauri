"""GET /api/v1/meetings/ exposes a signed thumbnail link, owner-scoped; deletion removes the frame."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SessionRecording
from app.meetings import router
from app.meetings.signed_urls import signed_url_ttl_seconds

OWNER_ID = "thumb-owner"
OTHER_ID = "thumb-other"


def _auth_header(user_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Thumbnail Test", True)
    return {"Authorization": f"Bearer {token}"}


class _Store:
    def __init__(self) -> None:
        self.signed: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.fail_signing = False

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        if self.fail_signing:
            raise RuntimeError("cannot sign")
        self.signed.append((reference, ttl_seconds))
        return f"https://storage.invalid/{reference}?X-Amz-Signature=abc"

    async def delete(self, reference: str) -> None:
        self.deleted.append(reference)


async def _seed(
    api_db_url: str,
    *,
    owner: str = OWNER_ID,
    presence: str = "muxed",
    state: str | None = "ready",
    with_recording: bool = True,
) -> tuple[str, str]:
    engine = create_async_engine(api_db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    meeting_id, recording_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="completed",
            created_by=owner, created_at=now, title="Synthetic",
        ))
        await session.flush()
        if with_recording:
            session.add(SessionRecording(
                id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
                capture_origin="web_upload", audio_ref="private/audio", video_ref=None,
                duration_seconds=0, interrupted=False, finished_at=now, video_presence=presence,
                thumbnail_state=state,
                thumbnail_ref=f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg" if state == "ready" else None,
            ))
    await engine.dispose()
    return meeting_id, recording_id


def _by_id(body: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["meeting_id"]: item for item in body}


@pytest.mark.asyncio
async def test_a_ready_thumbnail_is_listed_as_a_short_lived_signed_url(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, recording_id = await _seed(api_db_url)

    item = _by_id((await api_client.get("/api/v1/meetings/", headers=_auth_header())).json())[meeting_id]

    key = f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg"
    assert item["thumbnail_url"] == f"https://storage.invalid/{key}?X-Amz-Signature=abc"
    assert item["media_kind"] == "video"
    assert store.signed == [(key, signed_url_ttl_seconds())]
    assert "thumbnail_ref" not in item


@pytest.mark.asyncio
async def test_other_users_never_receive_the_link(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, _ = await _seed(api_db_url, owner=OWNER_ID)

    other = (await api_client.get("/api/v1/meetings/", headers=_auth_header(OTHER_ID))).json()

    assert other == []
    assert store.signed == []
    assert meeting_id not in str(other)


@pytest.mark.asyncio
async def test_the_listing_requires_authentication(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/meetings/")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("presence", "state", "expected_kind"),
    [
        ("absent", "audio_only", "audio"),
        ("absent", None, "audio"),
        ("unknown", "audio_only", "audio"),
        ("unknown", "ready", "video"),
        ("unknown", None, None),
        ("muxed", "unavailable", "video"),
        ("separate", None, "video"),
    ],
)
async def test_only_ready_thumbnails_have_a_url_and_media_kind_follows_the_evidence(
    api_client: AsyncClient,
    api_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    presence: str,
    state: str | None,
    expected_kind: str | None,
) -> None:
    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, _ = await _seed(api_db_url, presence=presence, state=state)

    item = _by_id((await api_client.get("/api/v1/meetings/", headers=_auth_header())).json())[meeting_id]

    assert item["media_kind"] == expected_kind
    assert (item["thumbnail_url"] is not None) == (state == "ready")


@pytest.mark.asyncio
async def test_a_meeting_without_recording_has_null_fields_and_needs_no_object_store(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _forbidden() -> None:
        raise AssertionError("no thumbnail to sign, the store must not be created")

    monkeypatch.setattr(router, "_get_object_store", _forbidden)
    meeting_id, _ = await _seed(api_db_url, with_recording=False)

    item = _by_id((await api_client.get("/api/v1/meetings/", headers=_auth_header())).json())[meeting_id]

    assert item["thumbnail_url"] is None and item["media_kind"] is None
    for kept in ("duration_seconds", "speaker_count", "summary_topic", "title", "process_state"):
        assert kept in item


@pytest.mark.asyncio
async def test_a_signing_failure_degrades_the_row_without_failing_the_list(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Store()
    store.fail_signing = True
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, _ = await _seed(api_db_url)

    response = await api_client.get("/api/v1/meetings/", headers=_auth_header())

    assert response.status_code == 200
    item = _by_id(response.json())[meeting_id]
    assert item["thumbnail_url"] is None and item["media_kind"] == "video"


@pytest.mark.asyncio
async def test_deleting_a_meeting_deletes_its_thumbnail_object(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, recording_id = await _seed(api_db_url)

    response = await api_client.delete(f"/api/v1/meetings/{meeting_id}", headers=_auth_header())

    assert response.status_code == 204
    assert f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg" in store.deleted
    assert "private/audio" in store.deleted


@pytest.mark.asyncio
async def test_deleting_a_meeting_without_a_thumbnail_deletes_only_the_media(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Store()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, _ = await _seed(api_db_url, presence="absent", state="audio_only")

    assert (await api_client.delete(f"/api/v1/meetings/{meeting_id}", headers=_auth_header())).status_code == 204
    assert store.deleted == ["private/audio"]
