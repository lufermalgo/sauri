"""HTTP privacy regressions for the opt-in projection; no acoustic qualification."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infra.models import Diarization
from tests.meetings import conftest as meeting_fixtures
from tests.speaker_review.test_generation_api import _auth, _seed

api_client = meeting_fixtures.api_client
api_db_url = meeting_fixtures.api_db_url


@pytest.mark.asyncio
async def test_v2_projection_requires_auth_and_hides_foreign_meeting(
    api_client: AsyncClient, api_db_url: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed"])
    generation = data["generations"][1]
    engine = create_async_engine(api_db_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            diarization = await session.get(Diarization, generation["diarization"])
            assert diarization is not None
            projection = {
                "version": 2,
                "transcript_id": diarization.transcript_id,
                "diarization_id": diarization.id,
                "processing_revision": 2,
                "policy_version": "exclusive-source-v1",
                "pieces": [{
                    "source_turn_id": data["turn"], "char_start": 0,
                    "char_end": len("Synthetic words"), "speaker_id": generation["speaker"],
                    "intervals": [{"start_ms": 0, "end_ms": 1000}],
                }],
            }
            diarization.presentation = projection
        path = f"/api/v1/meetings/{data['meeting']}/diarization?presentation_version=2"
        owner = await api_client.get(path, headers=_auth())
        assert owner.status_code == 200
        assert owner.json()["presentation"] == projection
        for private in ("prepared_result", "raw_label", "PRIVATE_ENGINE_LABEL", "Synthetic words"):
            assert private not in owner.text
        for headers in ({}, {"Authorization": "Bearer invalid-token"}):
            denied = await api_client.get(path, headers=headers)
            assert denied.status_code == 401
            for marker in (data["meeting"], data["turn"], generation["speaker"], "pieces"):
                assert marker not in denied.text
        foreign = await api_client.get(path, headers=_auth("another-owner"))
        missing = await api_client.get(
            f"/api/v1/meetings/{uuid.uuid4()}/diarization?presentation_version=2",
            headers=_auth("another-owner"),
        )
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        for marker in (data["meeting"], data["turn"], generation["speaker"], "pieces"):
            assert marker not in foreign.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_review_write_matches_missing_and_cannot_mutate_owner(
    api_client: AsyncClient, api_db_url: str,
) -> None:
    data = await _seed(api_db_url, ["completed", "completed"])
    generation = data["generations"][1]
    path = f"/api/v1/meetings/{data['meeting']}/speaker-review"
    before = await api_client.get(path, headers=_auth())
    assert before.status_code == 200
    payload = {
        "disposition": "named", "label": "Synthetic intruder",
        "expected_version": 1, "idempotency_key": "foreign-write",
    }
    suffix = f"/revisions/2/speakers/{generation['speaker']}"
    foreign = await api_client.put(path + suffix, json=payload, headers=_auth("another-owner"))
    missing = await api_client.put(
        f"/api/v1/meetings/{uuid.uuid4()}/speaker-review{suffix}",
        json=payload, headers=_auth("another-owner"),
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    for marker in (generation["speaker"], data["meeting"], payload["label"]):
        assert marker not in foreign.text
    after = await api_client.get(path, headers=_auth())
    assert after.status_code == 200
    assert after.json() == before.json()
