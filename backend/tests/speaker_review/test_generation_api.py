"""U9 revision-scoped review writes and word labels on migrated PostgreSQL.

PUT contracts adapted from closed PR #850; obsolete revisions now conflict,
and every response retains all speakers, including disposed ones.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.diarization.repository import DiarizationRepository
from app.infra.models import (
    MeetingProcessingClaim,
    Speaker,
    SpeakerReview,
    SpeakerReviewIdempotencyReceipt,
    SpeakerReviewItem,
)
from app.meetings.speaker_review_service import SpeakerReviewService
from tests.meetings import test_transcript_word_turns as word_tests

# Reuse the disposable, Alembic-migrated PostgreSQL fixtures, not the owner's DB.
migrated_url = word_tests.migrated_url
factory = word_tests.factory
client = word_tests.client
Factory = word_tests.Factory


async def _seed(factory: Factory) -> tuple[str, str, list[str]]:
    meeting, transcript = await word_tests._seed_meeting(factory)
    diarization, speakers = await word_tests._add_diarization(factory, meeting, transcript, 1, "completed")
    await word_tests._add_words(factory, transcript, diarization, speakers)
    await _review(factory, meeting, 1, list(speakers.values()))
    async with factory() as session, session.begin():
        # Worker fencing generations are independent of diarization revisions.
        session.add(MeetingProcessingClaim(meeting_id=meeting, generation=7))
    return meeting, transcript, list(speakers.values())


async def _review(factory: Factory, meeting: str, revision: int, speakers: list[str]) -> None:
    async with factory() as session, session.begin():
        review = SpeakerReview(id=str(uuid.uuid4()), meeting_id=meeting, processing_revision=revision,
                               status="pending", created_at=datetime.now(UTC))
        session.add(review)
        await session.flush()
        for sequence, speaker in enumerate(speakers, 1):
            session.add(SpeakerReviewItem(
                id=str(uuid.uuid4()), review_id=review.id, speaker_key=speaker,
                current_label=f"Speaker {sequence}", attribution_state="uncertain", version=1,
            ))


def _root(meeting: str) -> str:
    return f"/api/v1/meetings/{meeting}/speaker-review"


def _path(meeting: str, speaker: str, revision: int = 1) -> str:
    return f"{_root(meeting)}/revisions/{revision}/speakers/{speaker}"


def _payload(disposition: str = "confirmed", version: int = 1, **kwargs: Any) -> dict[str, Any]:
    return {"disposition": disposition, "expected_version": version,
            "idempotency_key": str(uuid.uuid4()), **kwargs}


async def _get(client: AsyncClient, meeting: str) -> dict[str, Any]:
    response = await client.get(_root(meeting), headers=word_tests._headers())
    assert response.status_code == 200
    return response.json()


async def test_named_corrected_confirmed_replay_and_completion(client: AsyncClient, factory: Factory) -> None:
    meeting, _, speakers = await _seed(factory)
    initial = await _get(client, meeting)
    assert set(initial) == {"review_id", "revision_id", "status", "items", "labels_by_speaker_id"}
    assert initial["labels_by_speaker_id"] == dict(zip(speakers, ["Speaker 1", "Speaker 2"], strict=True))
    assert initial["status"] == "pending"
    assert all(set(item) == {"speaker_id", "current_label", "attribution_state", "disposition", "version"}
               for item in initial["items"])
    first, second = speakers
    named = _payload("named", label=" Synthetic Alice ")
    response = await client.put(_path(meeting, first), json=named, headers=word_tests._headers())
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot == await _get(client, meeting)
    assert snapshot["status"] == "pending"
    items = {item["speaker_id"]: item for item in snapshot["items"]}
    assert items[first]["version"] == 2
    assert items[first]["disposition"] == "named"
    assert items[second] == next(item for item in initial["items"] if item["speaker_id"] == second)
    assert snapshot["labels_by_speaker_id"][first] == "Synthetic Alice"

    corrected = await client.put(_path(meeting, first), json=_payload("corrected", 2, label="Synthetic Bob"),
                                 headers=word_tests._headers())
    assert corrected.status_code == 200
    assert corrected.json()["labels_by_speaker_id"][first] == "Synthetic Bob"
    assert corrected.json()["status"] == "pending"
    confirmed = await client.put(_path(meeting, second), json=_payload(), headers=word_tests._headers())
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "complete"
    assert confirmed.json() == await _get(client, meeting)

    # Replay returns the original whole response even after later writes.
    replay = await client.put(_path(meeting, first), json=named, headers=word_tests._headers())
    assert replay.status_code == 200 and replay.json() == snapshot
    assert (await _get(client, meeting)) == confirmed.json()
    async with factory() as session:
        receipts = await session.scalar(select(func.count()).select_from(SpeakerReviewIdempotencyReceipt)
                                        .where(SpeakerReviewIdempotencyReceipt.review_id == initial["review_id"]))
        assert receipts == 3
        review = await session.get(SpeakerReview, initial["review_id"])
        assert review is not None and review.status == "complete"


async def test_conflicts_and_authorization_do_not_mutate(client: AsyncClient, factory: Factory) -> None:
    meeting, _, speakers = await _seed(factory)
    payload = _payload("named", label="Synthetic Alice")
    path = _path(meeting, speakers[0])
    for headers, status in [({}, 401), (word_tests._headers("another-owner"), 404)]:
        response = await client.put(path, json=payload, headers=headers)
        assert response.status_code == status
    applied = await client.put(path, json=payload, headers=word_tests._headers())
    assert applied.status_code == 200
    for target, body in [
        (path, {**payload, "label": "Synthetic Mallory"}),
        (path, {**payload, "idempotency_key": "stale"}),
        (_path(meeting, speakers[1]), payload),
        (_path(meeting, speakers[0], 99), payload),
    ]:
        response = await client.put(target, json=body, headers=word_tests._headers())
        assert response.status_code == 409
    missing = await client.put(_path(meeting, "unknown"), json=_payload(), headers=word_tests._headers())
    assert missing.status_code == 404
    assert await _get(client, meeting) == applied.json()


@pytest.mark.parametrize("body", [
    _payload("named"), _payload("corrected", label="  "), _payload("invalid"),
    _payload(status="complete"), _payload(version=0), _payload(version=True),
    _payload("named", label="x" * 65), _payload(idempotency_key=""),
])
async def test_invalid_input_is_rejected(client: AsyncClient, factory: Factory, body: dict[str, Any]) -> None:
    meeting, _, speakers = await _seed(factory)
    before = await _get(client, meeting)
    response = await client.put(_path(meeting, speakers[0]), json=body, headers=word_tests._headers())
    assert response.status_code == 422
    assert await _get(client, meeting) == before


@pytest.mark.parametrize("state", ["pending", "in_progress", "failed", "not_reconstructible", "completed"])
async def test_only_latest_completed_revision_is_active(
    client: AsyncClient, factory: Factory, state: str,
) -> None:
    meeting, transcript, speakers = await _seed(factory)
    payload = _payload("named", label="Synthetic Alice")
    applied = await client.put(_path(meeting, speakers[0]), json=payload, headers=word_tests._headers())
    assert applied.status_code == 200
    _, new_speakers = await word_tests._add_diarization(factory, meeting, transcript, 2, state)
    if state == "completed":
        await _review(factory, meeting, 2, list(new_speakers.values()))
    active = await _get(client, meeting)
    assert active["revision_id"] == (2 if state == "completed" else 1)
    # Even an old receipt cannot authorize a write to an obsolete revision.
    response = await client.put(_path(meeting, speakers[0]), json=payload, headers=word_tests._headers())
    assert response.status_code == (409 if state == "completed" else 200)
    assert await _get(client, meeting) == active
    if state == "completed":
        assert set(active["labels_by_speaker_id"]) == set(new_speakers.values())
        assert set(active["labels_by_speaker_id"].values()) == {"Speaker 1", "Speaker 2"}


async def test_word_turns_use_chosen_name_only_from_their_revision(client: AsyncClient, factory: Factory) -> None:
    meeting, transcript, speakers = await _seed(factory)
    url = f"/api/v1/meetings/{meeting}/transcript"
    before = (await client.get(url, headers=word_tests._headers())).json()["turns"]
    assert [turn["speaker_label"] for turn in before] == ["Speaker 1", "Speaker 2", "Speaker 2"]
    response = await client.put(_path(meeting, speakers[1]),
                                json=_payload("named", label="Synthetic Alice"), headers=word_tests._headers())
    assert response.status_code == 200
    after = (await client.get(url, headers=word_tests._headers())).json()["turns"]
    assert [turn["speaker_label"] for turn in after] == ["Speaker 1", "Synthetic Alice", "Synthetic Alice"]
    # A newer review containing the same key must not label words from revision 1.
    await _review(factory, meeting, 2, speakers)
    async with factory() as session, session.begin():
        review = await session.scalar(select(SpeakerReview).where(SpeakerReview.meeting_id == meeting,
                                                                 SpeakerReview.processing_revision == 2))
        assert review is not None
        item = await session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == review.id,
                                                                   SpeakerReviewItem.speaker_key == speakers[1]))
        assert item is not None
        item.chosen_label = "Wrong revision name"
    assert (await client.get(url, headers=word_tests._headers())).json()["turns"] == after


@pytest.mark.parametrize("same_key", [True, False])
async def test_concurrent_writes_are_serialized(client: AsyncClient, factory: Factory, same_key: bool) -> None:
    meeting, _, speakers = await _seed(factory)
    payload = _payload("named", label="Synthetic Alice")
    other = payload if same_key else {**payload, "idempotency_key": "other-key"}
    responses = await asyncio.gather(*[
        client.put(_path(meeting, speakers[0]), json=body, headers=word_tests._headers())
        for body in (payload, other)
    ])
    assert sorted(response.status_code for response in responses) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert responses[0].json() == responses[1].json()
    active = await _get(client, meeting)
    assert next(item for item in active["items"] if item["speaker_id"] == speakers[0])["version"] == 2
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpeakerReviewIdempotencyReceipt)
                                    .where(SpeakerReviewIdempotencyReceipt.review_id == active["review_id"])) == 1


async def test_publication_fences_a_waiting_old_revision_write(client: AsyncClient, factory: Factory) -> None:
    meeting, transcript, speakers = await _seed(factory)
    repo = DiarizationRepository(factory)
    async with factory() as session, session.begin():
        attempt = await repo.reserve_next_revision(session, meeting, transcript)
        assert await repo.claim_revision(session, meeting, attempt.processing_revision)
        revision, diarization_id = attempt.processing_revision, attempt.id

    async def write() -> dict[str, Any]:
        async with factory() as session, session.begin():
            return await SpeakerReviewService(session).record_disposition(
                word_tests.OWNER, meeting, "1", speakers[0], _payload(), 1,
            )

    task = None
    try:
        async with factory() as publishing, publishing.begin():
            publisher_pid = await publishing.scalar(text("SELECT pg_backend_pid()"))
            # Hold the same attempt lock used by complete_revision before starting the writer.
            await publishing.execute(text("SELECT id FROM diarizations WHERE id = :id FOR UPDATE"),
                                     {"id": diarization_id})
            task = asyncio.create_task(write())
            async with asyncio.timeout(5), factory() as observer:
                while not await observer.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                ), {"pid": publisher_pid}):
                    await asyncio.sleep(0.01)
            await repo.complete_revision(publishing, meeting, revision, "synthetic", [Speaker(
                id=str(uuid.uuid4()), diarization_id=diarization_id, raw_label="SPEAKER_00",
                label="Speaker 1", sequence=1,
            )], [])
        assert (await asyncio.wait_for(task, 5))["outcome"] == "conflict_stale_revision"
        assert (await _get(client, meeting))["revision_id"] == revision
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
