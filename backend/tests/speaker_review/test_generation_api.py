"""T13: synthetic wire contracts for generation-scoped diarization and review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    Transcript,
)
from app.meetings.speaker_review_service import SpeakerReviewService
from tests.meetings import conftest as meeting_fixtures

# Reuse the isolated file-backed API fixtures without changing global fixtures.
api_client = meeting_fixtures.api_client
api_db_url = meeting_fixtures.api_db_url

OWNER = "generation-contract-owner"


def _auth(owner: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(owner, 'test@sauri.local', 'Test', True)}"}


async def _seed(url: str, states: list[str]) -> dict[str, Any]:
    """Persist real model rows; no mocked selection or HTTP handlers."""
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    meeting, transcript, turn = (str(uuid.uuid4()) for _ in range(3))
    now = datetime.now(UTC)
    generations = []
    try:
        async with factory() as session, session.begin():
            session.add(
                Meeting(
                    id=meeting,
                    meet_link="https://meet.google.com/abc-defg-hij",
                    origin="link",
                    process_state="completed",
                    created_by=OWNER,
                    created_at=now,
                )
            )
            session.add(
                Transcript(
                    id=transcript,
                    meeting_id=meeting,
                    language="es",
                    provider="local",
                    supports_turns=True,
                    created_at=now,
                )
            )
            session.add(
                SpeechTurn(
                    id=turn, transcript_id=transcript, text="Synthetic words", start_ms=0, end_ms=1000, sequence=0
                )
            )
            for revision, state in enumerate(states, 1):
                diarization, speaker, review = (str(uuid.uuid4()) for _ in range(3))
                session.add(
                    Diarization(
                        id=diarization,
                        meeting_id=meeting,
                        transcript_id=transcript,
                        processing_revision=revision,
                        is_legacy=revision == 1,
                        provider="local" if state == "completed" else None,
                        speaker_count=1 if state == "completed" else 0,
                        diarization_state=state,
                        failure_cause="audio_unavailable" if state == "not_reconstructible" else None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if state == "completed":
                    session.add(
                        Speaker(
                            id=speaker,
                            diarization_id=diarization,
                            raw_label="PRIVATE_ENGINE_LABEL",
                            label="Speaker 1",
                            sequence=1,
                        )
                    )
                    session.add(
                        SpeakerAssignment(
                            id=str(uuid.uuid4()),
                            diarization_id=diarization,
                            turn_id=turn,
                            speaker_id=speaker,
                            overlap_ms=None if revision == 1 else 750,
                        )
                    )
                    session.add(
                        SpeakerReview(
                            id=review,
                            meeting_id=meeting,
                            processing_revision=revision,
                            status="pending",
                            created_at=now,
                        )
                    )
                    session.add(
                        SpeakerReviewItem(
                            id=str(uuid.uuid4()),
                            review_id=review,
                            speaker_key=speaker,
                            current_label="Speaker 1",
                            disposition=None,
                            attribution_state="uncertain",
                            version=1,
                        )
                    )
                generations.append({"diarization": diarization, "speaker": speaker, "review": review})
        return {"meeting": meeting, "turn": turn, "generations": generations}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", ["pending", "in_progress", "failed", "not_reconstructible", "completed"])
@pytest.mark.parametrize("query", ["", "?presentation_version=2"])
async def test_t13_latest_attempt_does_not_replace_completed_generation(
    api_client: AsyncClient,
    api_db_url: str,
    latest: str,
    query: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed", latest])
    response = await api_client.get(f"/api/v1/meetings/{data['meeting']}/diarization{query}", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    active = 3 if latest == "completed" else 2
    assert body["processing_revision"] == active
    assert body["diarization_id"] == data["generations"][active - 1]["diarization"]
    assert body["assignments"] == [
        {"turn_id": data["turn"], "speaker_id": data["generations"][active - 1]["speaker"], "overlap_ms": 750}
    ]
    assert body["latest_attempt"] == {
        "processing_revision": 3,
        "diarization_state": latest,
        "failure_cause": "audio_unavailable" if latest == "not_reconstructible" else None,
    }
    assert "PRIVATE_ENGINE_LABEL" not in response.text
    assert "Synthetic words" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "failed", "not_reconstructible"])
async def test_t13_no_completed_generation_has_empty_attribution(
    api_client: AsyncClient,
    api_db_url: str,
    state: str,
) -> None:
    data = await _seed(api_db_url, [state])
    response = await api_client.get(f"/api/v1/meetings/{data['meeting']}/diarization", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert body["processing_revision"] is None
    assert body["speakers"] == []
    assert body["assignments"] == []
    assert body["latest_attempt"]["diarization_state"] == state
    assert body["latest_attempt"]["processing_revision"] == 1


@pytest.mark.asyncio
async def test_t13_legacy_overlap_remains_null(api_client: AsyncClient, api_db_url: str) -> None:
    data = await _seed(api_db_url, ["completed"])
    response = await api_client.get(f"/api/v1/meetings/{data['meeting']}/diarization", headers=_auth())
    assert response.status_code == 200
    assert response.json()["assignments"][0]["overlap_ms"] is None
    assert response.json()["processing_revision"] == 1


@pytest.mark.asyncio
async def test_t13_active_and_historical_review_are_revision_scoped(
    api_client: AsyncClient,
    api_db_url: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed", "failed"])
    path = f"/api/v1/meetings/{data['meeting']}/speaker-review"
    active = await api_client.get(path, headers=_auth())
    assert active.status_code == 200
    assert active.json()["revision_id"] == 2
    historical = await api_client.get(path, params={"revision_id": 1}, headers=_auth())
    assert historical.status_code == 200
    assert historical.json()["revision_id"] == 1
    assert historical.json()["review_id"] == data["generations"][0]["review"]
    assert historical.json()["labels_by_speaker_id"] == {data["generations"][0]["speaker"]: "Speaker 1"}
    missing = await api_client.get(path, params={"revision_id": 99}, headers=_auth())
    assert missing.status_code == 404
    again = await api_client.get(path, headers=_auth())
    assert again.json()["revision_id"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["named", "corrected"])
async def test_t13_put_returns_complete_snapshot_and_replays_original(
    api_client: AsyncClient,
    api_db_url: str,
    disposition: str,
) -> None:
    data = await _seed(api_db_url, ["completed"])
    speaker = data["generations"][0]["speaker"]
    path = f"/api/v1/meetings/{data['meeting']}/speaker-review"
    payload = {
        "disposition": disposition,
        "label": "Synthetic Alice",
        "expected_version": 1,
        "idempotency_key": f"t13-{disposition}",
    }
    url = f"{path}/revisions/1/speakers/{speaker}"
    response = await api_client.put(url, headers=_auth(), json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["labels_by_speaker_id"] == {speaker: "Synthetic Alice"}
    assert body["items"] == []
    assert body["remaining_speaker_ids"] == []
    assert body["status"] == "complete"
    replay = await api_client.put(url, headers=_auth(), json=payload)
    assert replay.status_code == 200
    assert replay.json() == body
    reload = await api_client.get(path, headers=_auth())
    assert reload.json()["labels_by_speaker_id"] == body["labels_by_speaker_id"]


@pytest.mark.asyncio
async def test_t13_labels_include_disposed_and_pending_items(api_client: AsyncClient, api_db_url: str) -> None:
    data = await _seed(api_db_url, ["completed"])
    review = data["generations"][0]["review"]
    first_speaker = data["generations"][0]["speaker"]
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            for key, disposition, chosen in [
                ("named", "named", "Synthetic Bob"),
                ("corrected", "corrected", "Synthetic Carol"),
                ("confirmed", "confirmed", None),
                ("uncertain", "uncertain", None),
            ]:
                session.add(
                    SpeakerReviewItem(
                        id=str(uuid.uuid4()),
                        review_id=review,
                        speaker_key=key,
                        current_label=f"Speaker {key}",
                        disposition=disposition,
                        chosen_label=chosen,
                        attribution_state="uncertain",
                        version=2,
                    )
                )
        response = await api_client.get(f"/api/v1/meetings/{data['meeting']}/speaker-review", headers=_auth())
        assert response.status_code == 200
        body = response.json()
        assert body["labels_by_speaker_id"] == {
            first_speaker: "Speaker 1",
            "named": "Synthetic Bob",
            "corrected": "Synthetic Carol",
            "confirmed": "Speaker confirmed",
            "uncertain": "Speaker uncertain",
        }
        assert body["remaining_speaker_ids"] == [first_speaker]
        assert body["items"] == [
            {
                "speaker_id": first_speaker,
                "current_label": "Speaker 1",
                "attribution_state": "uncertain",
                "disposition": None,
                "excerpt_ref": None,
                "expected_version": 1,
            }
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_t13_service_receipt_preserves_aggregate_map(api_db_url: str) -> None:
    data = await _seed(api_db_url, ["completed"])
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    payload = {
        "disposition": "named",
        "label": "Synthetic Alice",
        "expected_version": 1,
        "idempotency_key": "service-t13",
    }
    args = (OWNER, data["meeting"], "1", data["generations"][0]["speaker"], payload, 1)
    try:
        async with factory() as session, session.begin():
            applied = await SpeakerReviewService(session).record_disposition(*args)
        async with factory() as session, session.begin():
            replay = await SpeakerReviewService(session).record_disposition(*args)
        assert applied["outcome"] == "apply"
        assert replay["outcome"] == "replay"
        assert replay["result"] == applied["result"]
        assert applied["result"]["labels_by_speaker_id"] == {args[3]: "Synthetic Alice"}
        assert applied["result"]["items"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["diarization", "speaker-review", "speaker-review?revision_id=1"])
async def test_t13_generation_reads_keep_owner_and_auth_boundaries(
    api_client: AsyncClient,
    api_db_url: str,
    suffix: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed"])
    path = f"/api/v1/meetings/{data['meeting']}/{suffix}"
    unauthenticated = await api_client.get(path)
    assert unauthenticated.status_code == 401
    other_owner = await api_client.get(path, headers=_auth("other-owner"))
    assert other_owner.status_code == 404
    assert "Synthetic" not in other_owner.text
    assert data["generations"][0]["speaker"] not in other_owner.text


@pytest.mark.asyncio
async def test_t13_put_keeps_owner_and_auth_boundaries(api_client: AsyncClient, api_db_url: str) -> None:
    data = await _seed(api_db_url, ["completed"])
    speaker = data["generations"][0]["speaker"]
    path = f"/api/v1/meetings/{data['meeting']}/speaker-review/revisions/1/speakers/{speaker}"
    payload = {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "auth-t13"}
    unauthenticated = await api_client.put(path, json=payload)
    assert unauthenticated.status_code == 401
    other_owner = await api_client.put(path, json=payload, headers=_auth("other-owner"))
    assert other_owner.status_code == 404
    owner = await api_client.get(f"/api/v1/meetings/{data['meeting']}/speaker-review", headers=_auth())
    assert owner.json()["remaining_speaker_ids"] == [speaker]


@pytest.mark.asyncio
async def test_revision_write_isolated_and_stale_or_reused_key_conflicts(
    api_client: AsyncClient, api_db_url: str
) -> None:
    data = await _seed(api_db_url, ["completed", "completed"])
    first, second = data["generations"]
    root = f"/api/v1/meetings/{data['meeting']}/speaker-review"
    path = f"{root}/revisions/1/speakers/{first['speaker']}"
    payload = {
        "disposition": "named",
        "label": "Synthetic Alice",
        "expected_version": 1,
        "idempotency_key": "generation-1",
    }
    applied = await api_client.put(path, json=payload, headers=_auth())
    assert applied.status_code == 200
    assert applied.json()["labels_by_speaker_id"] == {first["speaker"]: "Synthetic Alice"}

    conflict = await api_client.put(path, json={**payload, "label": "Synthetic Mallory"}, headers=_auth())
    assert conflict.status_code == 409
    stale = await api_client.put(path, json={**payload, "idempotency_key": "different-key"}, headers=_auth())
    assert stale.status_code == 409
    active = await api_client.get(root, headers=_auth())
    historical = await api_client.get(root, params={"revision_id": 1}, headers=_auth())
    assert active.json()["labels_by_speaker_id"] == {second["speaker"]: "Speaker 1"}
    assert historical.json()["labels_by_speaker_id"] == {first["speaker"]: "Synthetic Alice"}


@pytest.mark.asyncio
async def test_put_rejects_derived_completion_and_missing_speaker(api_client: AsyncClient, api_db_url: str) -> None:
    data = await _seed(api_db_url, ["completed"])
    root = f"/api/v1/meetings/{data['meeting']}/speaker-review"
    path = f"{root}/revisions/1/speakers/{data['generations'][0]['speaker']}"
    payload = {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "completion-is-derived"}
    rejected = await api_client.put(path, json={**payload, "status": "complete"}, headers=_auth())
    assert rejected.status_code == 422
    unknown = await api_client.put(f"{root}/revisions/1/speakers/unknown", json=payload, headers=_auth())
    assert unknown.status_code == 404
    assert (await api_client.get(root, headers=_auth())).json()["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", ["pending", "in_progress", "failed", "not_reconstructible", "completed"])
async def test_processing_and_result_agree_on_current_attempt_without_losing_active_attribution(
    api_client: AsyncClient, api_db_url: str, latest: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed", latest])
    path = f"/api/v1/meetings/{data['meeting']}"
    status = await api_client.get(f"{path}/processing", headers=_auth())
    result = await api_client.get(f"{path}/diarization", headers=_auth())
    assert status.status_code == result.status_code == 200
    assert status.json()["execution"]["diarization_revision"] == 3
    assert result.json()["latest_attempt"]["processing_revision"] == 3
    assert status.json()["ready"] == (latest == "completed")
    assert result.json()["processing_revision"] == (3 if latest == "completed" else 2)
    assert "PRIVATE_ENGINE_LABEL" not in status.text
    assert "Synthetic words" not in status.text
