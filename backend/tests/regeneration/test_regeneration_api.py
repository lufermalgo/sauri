"""#1053: the explicit regenerate API (auth, conflicts, idempotency, state rules, stale hints).

The real FastAPI app and database are used; only the broker and the object store are fakes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingSummary,
    RegenerationOperation,
    SessionRecording,
    Speaker,
    SpeakerReview,
    SpeakerReviewItem,
    StateHistory,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
    User,
)
from app.main import app


class FakeQueue:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.fail = False

    async def connect(self) -> None:
        if self.fail:
            raise ConnectionError("broker down")

    async def disconnect(self) -> None:
        return None

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        self.published.append((topic, message))


class FakeStore:
    def __init__(self) -> None:
        self.availability = "available"

    async def inspect(self, reference: str) -> str:
        return self.availability


@dataclass
class Api:
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    queue: FakeQueue
    store: FakeStore
    owner: str
    other: str
    meeting: str
    template: str
    ids: dict[str, str] = field(default_factory=dict)

    def headers(self, user: str | None = None, *, sales: bool = True) -> dict[str, str]:
        user = user or self.owner
        return {"Authorization": f"Bearer {create_token(user, f'{user}@example.test', 'Synthetic', sales)}"}

    async def regenerate(self, body: dict[str, Any], **headers: str) -> Any:
        return await self.client.post(
            f"/api/v1/meetings/{self.meeting}/regenerate", json=body, headers={**self.headers(), **headers}
        )

    async def settle(self, operation_id: str, status: str = "succeeded") -> None:
        async with self.factory() as session, session.begin():
            op = await session.get(RegenerationOperation, operation_id)
            assert op is not None
            op.status, op.finished_at = status, datetime.now(UTC)


@pytest.fixture
async def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Api]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'regeneration.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner, other, meeting, recording, transcript, template = (str(uuid4()) for _ in range(6))
    now = datetime.now(UTC) - timedelta(hours=1)
    async with factory() as session, session.begin():
        for user in (owner, other):
            session.add(User(
                id=user, email=f"{user}@example.test", name="Synthetic", password_hash="x", is_sales=True,
                created_at=now,
            ))
        session.add(Meeting(
            id=meeting, origin="manual", process_state="completed", created_by=owner, created_at=now,
        ))
        session.add(SessionRecording(
            id=recording, meeting_id=meeting, idempotency_key=recording, capture_origin="web_upload",
            audio_ref="synthetic.webm", duration_seconds=6, interrupted=False, finished_at=now,
        ))
        session.add(Transcript(
            id=transcript, meeting_id=meeting, language="es", provider="synthetic", supports_turns=True, created_at=now,
        ))
        session.add(SummaryTemplate(
            id=template, owner_user_id=owner, name="Custom", instructions="Brief", version=1,
            created_at=now, updated_at=now,
        ))
        await session.flush()
        owner_row = await session.get(User, owner)
        assert owner_row is not None
        owner_row.default_summary_template_id = template
    queue, store = FakeQueue(), FakeStore()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setattr("app.regeneration.router._get_queue", lambda: queue)
    monkeypatch.setattr("app.regeneration.router._get_object_store", lambda: store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            api = Api(client, factory, queue, store, owner, other, meeting, template)
            api.ids.update(recording=recording, transcript=transcript)
            yield api
    finally:
        await engine.dispose()


async def add_diarization(
    api: Api, revision: int = 1, state: str = "completed", updated: datetime | None = None
) -> str:
    diarization_id = str(uuid4())
    now = updated or datetime.now(UTC) - timedelta(minutes=50)
    async with api.factory() as session, session.begin():
        session.add(Diarization(
            id=diarization_id, meeting_id=api.meeting, transcript_id=api.ids["transcript"],
            processing_revision=revision, diarization_state=state, speaker_count=1, created_at=now, updated_at=now,
        ))
    return diarization_id


async def add_summary(api: Api, generation: int = 1, created: datetime | None = None) -> str:
    event_id = str(uuid4())
    now = created or datetime.now(UTC) - timedelta(minutes=40)
    async with api.factory() as session, session.begin():
        session.add(SummaryRequestOutbox(
            event_id=event_id, meeting_id=api.meeting, transcript_id=api.ids["transcript"], template_id=api.template,
            template_version=1, instructions_snapshot="Brief", generation=generation, status="succeeded",
            delivered_at=now, requested_at=now, finished_at=now,
        ))
        await session.flush()
        session.add(MeetingSummary(
            id=str(uuid4()), event_id=event_id, meeting_id=api.meeting, transcript_id=api.ids["transcript"],
            template_id=api.template, template_version=1, generation=generation, topic="Old topic",
            key_points_json="[]", created_at=now, updated_at=now,
        ))
    return event_id


async def operations(api: Api) -> list[RegenerationOperation]:
    async with api.factory() as session:
        return list(await session.scalars(select(RegenerationOperation).order_by(RegenerationOperation.requested_at)))


# --- Validation, authorization, ownership ---------------------------------------------------


async def test_unknown_stage_is_rejected_with_422(api: Api) -> None:
    bodies: tuple[dict[str, Any], ...] = (
        {"stage": "audio"}, {}, {"stage": "summary", "cascade": True},
        {"stage": "speakers", "template_id": "t"}, {"stage": "summary", "extra": 1},
    )
    for body in bodies:
        assert (await api.regenerate(body)).status_code == 422, body
    assert await operations(api) == [] and api.queue.published == []


async def test_requires_an_authorized_owner(api: Api) -> None:
    path = f"/api/v1/meetings/{api.meeting}/regenerate"
    assert (await api.client.post(path, json={"stage": "summary"})).status_code in (401, 403)
    async with api.factory() as session, session.begin():  # The role is read from the account row.
        owner_row = await session.get(User, api.owner)
        assert owner_row is not None
        owner_row.is_sales = False
    denied = await api.client.post(path, json={"stage": "summary"}, headers=api.headers(sales=False))
    assert denied.status_code == 403
    async with api.factory() as session, session.begin():
        owner_row = await session.get(User, api.owner)
        assert owner_row is not None
        owner_row.is_sales = True
    foreign = await api.client.post(path, json={"stage": "summary"}, headers=api.headers(api.other))
    assert foreign.status_code == 404
    for suffix in ("latest", str(uuid4())):
        assert (await api.client.get(f"{path}/{suffix}", headers=api.headers(api.other))).status_code == 404
    assert await operations(api) == []


# --- Summary --------------------------------------------------------------------------------


async def test_summary_keeps_the_previous_one_visible_and_uses_the_default_template(api: Api) -> None:
    await add_summary(api)
    accepted = await api.regenerate({"stage": "summary"})
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert (body["stage"], body["status"], body["replaces"], body["stale"]) == ("summary", "accepted", ["summary"], [])
    assert api.queue.published == []  # the durable outbox delivers summaries
    async with api.factory() as session:
        request = await session.get(SummaryRequestOutbox, body["summary_request_id"])
        assert request is not None and request.template_id == api.template and request.generation == 2
        assert request.status == "pending"
    current = await api.client.get(f"/api/v1/meetings/{api.meeting}/summary", headers=api.headers())
    assert current.status_code == 200 and current.json()["topic"] == "Old topic"  # until the new one succeeds


async def test_summary_accepts_an_explicit_owned_template_and_rejects_a_foreign_one(api: Api) -> None:
    async with api.factory() as session, session.begin():
        session.add(SummaryTemplate(
            id="foreign", owner_user_id=api.other, name="F", instructions="x", version=1,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ))
    assert (await api.regenerate({"stage": "summary", "template_id": "foreign"})).status_code == 422
    assert (await api.regenerate({"stage": "summary", "template_id": api.template})).status_code == 202


async def test_summary_operation_follows_its_request(api: Api) -> None:
    body = (await api.regenerate({"stage": "summary"})).json()
    async with api.factory() as session, session.begin():
        request = await session.get(SummaryRequestOutbox, body["summary_request_id"])
        assert request is not None
        request.status, request.started_at = "running", datetime.now(UTC)
    running = (await api.client.get(
        f"/api/v1/meetings/{api.meeting}/regenerate/{body['operation_id']}", headers=api.headers())).json()
    assert running["status"] == "running" and "started_at" in running
    async with api.factory() as session, session.begin():
        request = await session.get(SummaryRequestOutbox, body["summary_request_id"])
        assert request is not None
        request.status, request.failure_cause, request.finished_at = "failed", "llm_unavailable", datetime.now(UTC)
    latest = (await api.client.get(f"/api/v1/meetings/{api.meeting}/regenerate/latest", headers=api.headers())).json()
    assert (latest["status"], latest["failure_cause"]) == ("failed", "llm_unavailable")
    assert (await operations(api))[0].status == "failed"  # the audit row settled too
    assert (await api.regenerate({"stage": "summary"})).status_code == 202  # the meeting is free again


async def test_summary_requires_a_transcript(api: Api) -> None:
    async with api.factory() as session, session.begin():
        await session.execute(delete(Transcript))
    rejected = await api.regenerate({"stage": "summary"})
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "transcript_unavailable"


# --- One active operation ------------------------------------------------------------------


async def test_a_second_request_gets_409_with_the_active_operation(api: Api) -> None:
    first = (await api.regenerate({"stage": "speakers"})).json()
    conflict = await api.regenerate({"stage": "summary"})
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "operation_active" and detail["operation"]["operation_id"] == first["operation_id"]
    assert len(await operations(api)) == 1


async def test_an_original_pipeline_in_flight_blocks_regeneration(api: Api) -> None:
    async with api.factory() as session, session.begin():
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None
        meeting.process_state = "transcribing"
        session.add(StateHistory(id=str(uuid4()), meeting_id=api.meeting, state="transcribing",
                                 occurred_at=datetime.now(UTC)))
    blocked = await api.regenerate({"stage": "speakers"})
    assert blocked.status_code == 409 and blocked.json()["detail"] == {
        "code": "processing_active", "active_stage": "transcription"}


async def test_a_stuck_old_run_does_not_block_forever(api: Api) -> None:
    old = datetime.now(UTC) - timedelta(hours=3)
    async with api.factory() as session, session.begin():
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None
        meeting.process_state = "transcribing"
        session.add(StateHistory(id=str(uuid4()), meeting_id=api.meeting, state="transcribing", occurred_at=old))
    await add_diarization(api, 1, "in_progress", updated=old)
    accepted = await api.regenerate({"stage": "speakers"})
    assert accepted.status_code == 202, accepted.text
    async with api.factory() as session:
        stuck = (await session.scalars(select(Diarization).where(Diarization.processing_revision == 1))).one()
        assert (stuck.diarization_state, stuck.failure_cause) == ("failed", "stale_operation")


async def test_an_active_summary_request_blocks_regeneration(api: Api) -> None:
    await api.regenerate({"stage": "summary"})
    async with api.factory() as session, session.begin():
        await session.execute(delete(RegenerationOperation))  # a request with no operation row
    blocked = await api.regenerate({"stage": "speakers"})
    assert blocked.status_code == 409 and blocked.json()["detail"]["active_stage"] == "summary"


# --- Idempotency ---------------------------------------------------------------------------


async def test_idempotency_key_replays_the_same_operation(api: Api) -> None:
    first = await api.regenerate({"stage": "speakers"}, **{"Idempotency-Key": "k-1"})
    await api.settle(first.json()["operation_id"], "failed")
    replay = await api.regenerate({"stage": "speakers"}, **{"Idempotency-Key": "k-1"})
    assert replay.status_code == 202 and replay.json()["operation_id"] == first.json()["operation_id"]
    assert len(await operations(api)) == 1 and len(api.queue.published) == 1
    reused = await api.regenerate({"stage": "summary"}, **{"Idempotency-Key": "k-1"})
    assert reused.status_code == 409 and reused.json()["detail"]["code"] == "idempotency_key_reused"
    stored = (await operations(api))[0].idempotency_key
    assert stored is not None and stored != "k-1" and len(stored) == 64  # only a digest is stored


# --- Speakers ------------------------------------------------------------------------------


async def test_speakers_reserve_a_new_revision_and_arm_a_fenced_claim(api: Api) -> None:
    await add_diarization(api)
    await add_summary(api)
    accepted = await api.regenerate({"stage": "speakers"})
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["replaces"] == ["speakers"] and body["stale"] == ["summary"]  # the UI may suggest the summary
    [(topic, message)] = api.queue.published
    assert topic == "diarize" and message["operation_id"] == body["operation_id"]
    assert message["processing_revision"] == 2 and message["generation"] == 1
    async with api.factory() as session:
        claim = await session.get(MeetingProcessingClaim, api.meeting)
        assert claim is not None and (claim.generation, claim.claim_id, claim.claim_kind) == (
            1, body["operation_id"], "recovery")
        revisions = {d.processing_revision: d.diarization_state for d in await session.scalars(select(Diarization))}
        assert revisions == {1: "completed", 2: "pending"}  # the previous revision is untouched
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1  # no summary chained


async def test_media_unavailable_is_409_for_transcription_and_speakers(api: Api) -> None:
    api.store.availability = "missing"
    for stage in ("transcription", "speakers"):
        rejected = await api.regenerate({"stage": stage})
        assert rejected.status_code == 409 and rejected.json()["detail"] == {"code": "media_unavailable"}
    async with api.factory() as session, session.begin():
        recording = (await session.scalars(select(SessionRecording))).one()
        recording.expires_at = datetime.now(UTC) - timedelta(days=1)
    api.store.availability = "available"
    assert (await api.regenerate({"stage": "speakers"})).json()["detail"] == {"code": "media_unavailable"}
    assert await operations(api) == [] and api.queue.published == []
    async with api.factory() as session:
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None and meeting.process_state == "completed"


async def test_storage_errors_are_503_not_a_wrong_conclusion(api: Api) -> None:
    async def broken(_: str) -> str:
        raise OSError("storage")

    api.store.inspect = broken  # type: ignore[method-assign,assignment]
    assert (await api.regenerate({"stage": "speakers"})).status_code == 503


# --- Transcription -------------------------------------------------------------------------


async def test_transcription_reopens_the_meeting_and_keeps_everything_visible(api: Api) -> None:
    await add_diarization(api)
    await add_summary(api)
    accepted = await api.regenerate({"stage": "transcription"})
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["replaces"] == ["transcription"] and body["stale"] == ["speakers", "summary"]
    assert body["cascade"] is False
    [(topic, message)] = api.queue.published
    assert topic == "transcribe" and message["operation_id"] == body["operation_id"]
    assert message["recording_id"] == api.ids["recording"] and message["audio_ref"] == "synthetic.webm"
    detail = (await api.client.get(f"/api/v1/meetings/{api.meeting}", headers=api.headers())).json()
    assert detail["process_state"] == "transcribing"  # the page must not say it is ready
    assert detail["active_operation"]["stage"] == "transcription"
    for visible in ("summary", "transcript"):
        assert (await api.client.get(f"/api/v1/meetings/{api.meeting}/{visible}", headers=api.headers())
                ).status_code == 200


async def test_cascade_is_recorded_and_defaults_to_off(api: Api) -> None:
    body = (await api.regenerate({"stage": "transcription", "cascade": True, "template_id": api.template})).json()
    assert body["cascade"] is True and body["replaces"] == ["transcription", "speakers", "summary"]
    assert body["stale"] == []
    stored = (await operations(api))[0]
    assert stored.cascade is True and stored.template_id == api.template


async def test_a_failed_meeting_can_be_retried_explicitly(api: Api) -> None:
    async with api.factory() as session, session.begin():
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None
        meeting.process_state, meeting.failure_cause = "failed", "engine_failure"
        await session.execute(delete(Transcript))
    accepted = await api.regenerate({"stage": "transcription"})
    assert accepted.status_code == 202, accepted.text
    async with api.factory() as session:
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None and meeting.process_state == "transcribing"


async def test_a_lost_message_fails_the_operation_and_restores_the_state(api: Api) -> None:
    api.queue.fail = True
    rejected = await api.regenerate({"stage": "transcription"})
    assert rejected.status_code == 503 and rejected.json()["detail"] == {"code": "queue_unavailable"}
    [op] = await operations(api)
    assert (op.status, op.failure_cause) == ("failed", "queue_unavailable")
    async with api.factory() as session:
        meeting = await session.get(Meeting, api.meeting)
        assert meeting is not None and meeting.process_state == "completed"  # previous outputs stay usable
    api.queue.fail = False
    assert (await api.regenerate({"stage": "transcription"})).status_code == 202


# --- Status and hints ----------------------------------------------------------------------


async def test_status_endpoints_and_meeting_hints(api: Api) -> None:
    assert (await api.client.get(f"/api/v1/meetings/{api.meeting}/regenerate/latest", headers=api.headers())
            ).status_code == 404
    detail = (await api.client.get(f"/api/v1/meetings/{api.meeting}", headers=api.headers())).json()
    assert "stale_stages" not in detail and "active_operation" not in detail  # omitted when empty
    body = (await api.regenerate({"stage": "speakers"})).json()
    by_id = await api.client.get(f"/api/v1/meetings/{api.meeting}/regenerate/{body['operation_id']}",
                                 headers=api.headers())
    latest = await api.client.get(f"/api/v1/meetings/{api.meeting}/regenerate/latest", headers=api.headers())
    assert by_id.json() == latest.json() and by_id.json()["requested_at"].endswith("Z")
    assert (await api.client.get(f"/api/v1/meetings/{api.meeting}/regenerate/nope", headers=api.headers())
            ).status_code == 404


async def test_stale_stages_come_only_from_explicit_operations(api: Api) -> None:
    await add_diarization(api)
    await add_summary(api)
    path = f"/api/v1/meetings/{api.meeting}"
    assert "stale_stages" not in (await api.client.get(path, headers=api.headers())).json()
    async with api.factory() as session, session.begin():
        session.add(RegenerationOperation(
            id=str(uuid4()), meeting_id=api.meeting, stage="transcription", status="succeeded",
            requested_by=api.owner, requested_at=datetime.now(UTC), finished_at=datetime.now(UTC), cascade=False,
        ))
    assert (await api.client.get(path, headers=api.headers())).json()["stale_stages"] == ["speakers", "summary"]
    await add_diarization(api, 2, updated=datetime.now(UTC) + timedelta(seconds=5))
    assert (await api.client.get(path, headers=api.headers())).json()["stale_stages"] == ["summary"]
    await add_summary(api, 2, created=datetime.now(UTC) + timedelta(seconds=10))
    assert "stale_stages" not in (await api.client.get(path, headers=api.headers())).json()


async def test_older_speaker_revision_stays_readable(api: Api) -> None:
    first = await add_diarization(api, 1)
    second = await add_diarization(api, 2)
    async with api.factory() as session, session.begin():
        for revision, diarization_id in ((1, first), (2, second)):
            speaker = f"speaker-{revision}"
            session.add(Speaker(
                id=speaker, diarization_id=diarization_id, raw_label="A", label="Speaker 1", sequence=1))
            review = SpeakerReview(id=f"review-{revision}", meeting_id=api.meeting, processing_revision=revision,
                                   status="complete" if revision == 1 else "pending", created_at=datetime.now(UTC))
            session.add(review)
            await session.flush()
            session.add(SpeakerReviewItem(
                id=f"item-{revision}", review_id=review.id, speaker_key=speaker, current_label="Speaker 1",
                disposition="named" if revision == 1 else None, chosen_label="Ana" if revision == 1 else None,
            ))
    path = f"/api/v1/meetings/{api.meeting}/speaker-review"
    active = (await api.client.get(path, headers=api.headers())).json()
    assert active["revision_id"] == 2 and active["status"] == "pending" and active["available_revisions"] == [1, 2]
    older = (await api.client.get(f"{path}?revision_id=1", headers=api.headers())).json()
    assert older["revision_id"] == 1 and older["status"] == "complete"
    assert older["labels_by_speaker_id"] == {"speaker-1": "Ana"}
    assert (await api.client.get(f"{path}?revision_id=9", headers=api.headers())).status_code == 404
