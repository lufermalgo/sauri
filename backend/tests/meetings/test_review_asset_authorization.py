"""Chrome completion T1.6 (#615): protect both assets of the same meeting.

Exercise real HTTP handlers and persisted synthetic assets; only URL signing is
replaced. Existing authorization should remain GREEN, not be broken for RED.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript
from app.meetings import router

OWNER = "review-asset-owner"


def _headers(owner: str = OWNER) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_token(
        owner, f"{owner}@sauri.local", "Synthetic Review", True,
    )}


class _SigningStore:
    def __init__(self) -> None:
        self.signed: list[str] = []

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        assert ttl_seconds == 900
        self.signed.append(reference)
        return f"https://media.example.test/signed/{len(self.signed)}"


@pytest.fixture
async def protected_assets(api_db_url: str) -> list[tuple[str, str, str]]:
    """Two same-owner meetings plus one other-owner meeting, all fully populated."""
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    assets = []
    try:
        async with factory() as session, session.begin():
            for owner in (OWNER, OWNER, "other-asset-owner"):
                meeting_id, transcript_id, recording_id = (str(uuid.uuid4()) for _ in range(3))
                text = f"Private synthetic transcript {transcript_id}"
                reference = f"private/{meeting_id}/muxed.webm"
                now = datetime.now(UTC)
                session.add(Meeting(
                    id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij",
                    origin="link", process_state="completed", created_by=owner, created_at=now,
                ))
                session.add(Transcript(
                    id=transcript_id, meeting_id=meeting_id, language="es-CO",
                    provider="synthetic", supports_turns=True, created_at=now,
                ))
                session.add(SpeechTurn(
                    id=str(uuid.uuid4()), transcript_id=transcript_id,
                    text=text, start_ms=0, end_ms=1000, sequence=0,
                ))
                session.add(SessionRecording(
                    id=recording_id, meeting_id=meeting_id, idempotency_key=recording_id,
                    capture_origin="chrome_extension", audio_ref=reference, video_ref=None,
                    video_presence="muxed", duration_seconds=1, interrupted=False, finished_at=now,
                ))
                assets.append((meeting_id, text, reference))
        return assets
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["transcript", "playback"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-token"}])
async def test_assets_require_authentication(
    api_client: AsyncClient, protected_assets: list[tuple[str, str, str]],
    monkeypatch: pytest.MonkeyPatch, endpoint: str, headers: dict[str, str],
) -> None:
    store = _SigningStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, text, reference = protected_assets[0]
    response = await api_client.get(f"/api/v1/meetings/{meeting_id}/{endpoint}", headers=headers)
    assert response.status_code == 401
    assert text not in response.text
    assert reference not in response.text
    assert meeting_id not in response.text
    assert store.signed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["transcript", "playback"])
async def test_other_owner_is_indistinguishable_from_missing_meeting(
    api_client: AsyncClient, protected_assets: list[tuple[str, str, str]],
    monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    store = _SigningStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    meeting_id, text, reference = protected_assets[2]
    denied = await api_client.get(f"/api/v1/meetings/{meeting_id}/{endpoint}", headers=_headers())
    missing = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}/{endpoint}", headers=_headers())
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    for marker in (meeting_id, text, reference, "segments", "audio_source", "muxed_video_source"):
        assert marker not in denied.text
    assert store.signed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["transcript", "playback"])
async def test_owner_receives_only_requested_meeting_assets(
    api_client: AsyncClient, protected_assets: list[tuple[str, str, str]],
    monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    store = _SigningStore()
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    for meeting_id, text, reference in protected_assets[:2]:
        store.signed.clear()
        response = await api_client.get(
            f"/api/v1/meetings/{meeting_id}/{endpoint}", headers=_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meeting_id"] == meeting_id
        if endpoint == "transcript":
            assert [segment["text"] for segment in body["segments"]] == [text]
            assert store.signed == []
        else:
            assert body["video_presence"] == "muxed"
            assert body["muxed_video_source"]["url"].startswith("https://media.example.test/signed/")
            assert store.signed == [reference]
            assert "private/" not in response.text
        for other_id, other_text, other_reference in protected_assets:
            if other_id != meeting_id:
                assert other_id not in response.text
                assert other_text not in response.text
                assert other_reference not in store.signed
