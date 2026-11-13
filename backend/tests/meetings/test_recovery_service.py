"""T17/T18 behavioral HTTP contracts; PostgreSQL is mandatory for lock evidence.

Set SAURI_RECOVERY_TEST_DATABASE_URL to an exclusively disposable local database
named recovery_771. No owner's database, broker, model or media is used.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.database import Base
from app.infra.models import (
    ManualRecoveryPilotGate,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingRecoveryOutbox,
    SessionRecording,
    StateHistory,
    Transcript,
    User,
)
from app.infra.processing_claims import claim_worker_generation
from app.meetings import router
from tests.meetings.test_manual_recovery_routes import OWNER_ID, _create_meeting, _headers


@pytest.fixture
async def api_db_url(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str, None]:
    url = os.environ.get("SAURI_RECOVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires exclusively temporary PostgreSQL SAURI_RECOVERY_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "recovery_771"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    try:
        yield url
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await engine.dispose()


@pytest.fixture
async def candidate(api_db_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str, None]:
    meeting_id = await _create_meeting(api_db_url)
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(User(id=OWNER_ID, email="synthetic@sauri.local", name="Synthetic",
                         password_hash="not-a-password", is_sales=True, created_at=now))
        session.add(SessionRecording(id=str(uuid.uuid4()), meeting_id=meeting_id,
                                     idempotency_key=str(uuid.uuid4()), capture_origin="web_upload",
                                     audio_ref="synthetic/private/audio", video_ref=None, duration_seconds=1,
                                     interrupted=False, finished_at=now, expires_at=now + timedelta(days=7)))
        session.add(MeetingProcessingClaim(meeting_id=meeting_id, generation=4))
    async with factory() as session, session.begin():
        session.add(ManualRecoveryPilotGate(id=1, status="disabled", allowed_meeting_id=meeting_id,
                                           authorized_by=OWNER_ID, armed_at=now, updated_at=now))
    monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "pilot")
    monkeypatch.setenv("SAURI_RECOVERY_PILOT_MEETING_ID", meeting_id)
    store = AsyncMock()
    store.inspect.return_value = "available"
    monkeypatch.setattr(router, "_get_object_store", lambda: store)
    queue = AsyncMock()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)
    yield meeting_id
    queue.publish.assert_not_awaited()
    queue.connect.assert_not_awaited()
    store.get.assert_not_awaited()
    await engine.dispose()


async def snapshot(url: str) -> dict[str, list[tuple[object, ...]]]:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        result = {}
        for table in Base.metadata.sorted_tables:
            rows = (await connection.execute(select(table))).all()
            result[table.name] = sorted([tuple(row) for row in rows], key=repr)
    await engine.dispose()
    return result


async def post(client: AsyncClient, meeting: str, key: str = "synthetic-key") -> dict[str, object]:
    response = await client.post(f"/api/v1/meetings/{meeting}/recover",
                                 headers={**_headers(OWNER_ID), "Idempotency-Key": key})
    assert response.status_code == 200
    assert "synthetic/private/audio" not in response.text
    assert "Synthetic recovery fixture title" not in response.text
    assert "synthetic-key" not in response.text
    return dict(response.json())


@pytest.mark.parametrize("state", ["queued", "transcribing"])
async def test_accepts_one_atomic_fenced_operation(
    api_client: AsyncClient, api_db_url: str, candidate: str, state: str,
) -> None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        meeting = await session.get(Meeting, candidate)
        assert meeting
        meeting.process_state = state
    before = await snapshot(api_db_url)
    body = await post(api_client, candidate)
    assert body["status"] == "accepted"
    after = await snapshot(api_db_url)
    async with factory() as session:
        operation = (await session.scalars(select(MeetingRecoveryOperation))).one()
        outbox = (await session.scalars(select(MeetingRecoveryOutbox))).one()
        gate = await session.get(ManualRecoveryPilotGate, 1)
        claim = await session.get(MeetingProcessingClaim, candidate)
        meeting = await session.get(Meeting, candidate)
        history = (await session.scalars(select(StateHistory))).one()
        assert gate and claim and meeting
        assert body["operation_id"] == operation.id == gate.pilot_operation_id == claim.claim_id
        assert gate.status == "running" and gate.allowed_meeting_id == candidate
        assert operation.meeting_id == candidate and operation.actor_id == OWNER_ID
        assert operation.idempotency_key == hashlib.sha256(b"synthetic-key").hexdigest()
        assert operation.processing_generation == claim.generation == outbox.processing_generation == 5
        assert claim.claim_kind == "recovery"
        assert outbox.operation_id == operation.id and outbox.delivery_status == "pending"
        assert outbox.job_identifiers == {}  # resolved from persisted recording, never caller input
        assert meeting.process_state == history.state == "transcribing"
    for table in before.keys() - {"meetings", "meeting_processing_claims", "meeting_recovery_operations",
                                 "meeting_recovery_outbox", "manual_recovery_pilot_gate", "state_history"}:
        assert before[table] == after[table], table
    assert before["meetings"][0][:7] == after["meetings"][0][:7]  # note/title and identity preserved
    await engine.dispose()


@pytest.mark.parametrize(("case", "reason"), [
    ("disabled", "pilot_not_armed"), ("wrong_allowlist", "pilot_not_armed"),
    ("missing_allowlist", "pilot_not_armed"), ("missing_gate", "pilot_not_armed"),
    ("wrong_gate", "pilot_not_armed"), ("used_gate", "pilot_in_use"),
    ("wrong_state", "ineligible_state"), ("missing_recording", "eligibility_unverified"),
    ("empty_audio", "eligibility_unverified"), ("expired_recording", "eligibility_unverified"),
    ("transcript", "ineligible_artifacts"), ("missing_fence", "eligibility_unverified"),
    ("active_claim", "active_or_pending_work"), ("expired_claim", "active_or_pending_work"),
    ("partial_claim", "active_or_pending_work"), ("object_missing", "eligibility_unverified"),
    ("object_unknown", "eligibility_unverified"), ("object_error", "eligibility_unverified"),
])
async def test_rejects_without_any_database_write(
    api_client: AsyncClient, api_db_url: str, candidate: str, monkeypatch: pytest.MonkeyPatch,
    case: str, reason: str,
) -> None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        gate = await session.get(ManualRecoveryPilotGate, 1)
        claim = await session.get(MeetingProcessingClaim, candidate)
        recording = (await session.scalars(select(SessionRecording))).one()
        meeting = await session.get(Meeting, candidate)
        assert gate and claim and meeting
        if case == "disabled":
            monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "disabled")
        elif case == "wrong_allowlist":
            monkeypatch.setenv("SAURI_RECOVERY_PILOT_MEETING_ID", str(uuid.uuid4()))
        elif case == "missing_allowlist":
            monkeypatch.delenv("SAURI_RECOVERY_PILOT_MEETING_ID")
        elif case == "missing_gate":
            await session.delete(gate)
        elif case == "wrong_gate":
            gate.allowed_meeting_id = None
        elif case == "used_gate":
            gate.status = "awaiting_verification"
        elif case == "wrong_state":
            meeting.process_state = "completed"
        elif case == "missing_recording":
            await session.delete(recording)
        elif case == "empty_audio":
            recording.audio_ref = " "
        elif case == "expired_recording":
            recording.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif case == "transcript":
            session.add(Transcript(id=str(uuid.uuid4()), meeting_id=candidate, language="es",
                                   provider="synthetic", supports_turns=False, created_at=datetime.now(UTC)))
        elif case == "missing_fence":
            await session.delete(claim)
        elif case in {"active_claim", "expired_claim"}:
            claim.claim_id = str(uuid.uuid4())
            claim.claim_kind = "transcription"
            if case == "expired_claim":
                claim.claim_expires_at = datetime.now(UTC) - timedelta(days=1)
        elif case == "partial_claim":
            claim.claim_kind = "diarization"
        elif case.startswith("object_"):
            store = router._get_object_store()
            if case == "object_error":
                store.inspect.side_effect = RuntimeError("private-storage-error")
            else:
                store.inspect.return_value = "missing" if case == "object_missing" else None
    before = await snapshot(api_db_url)
    body = await post(api_client, candidate)
    assert body == {"status": reason, "reason_code": reason}
    assert await snapshot(api_db_url) == before
    await engine.dispose()


async def test_same_key_is_stable_and_distinct_key_cannot_consume_gate(
    api_client: AsyncClient, api_db_url: str, candidate: str,
) -> None:
    first = await post(api_client, candidate)
    assert first["status"] == "accepted"
    before = await snapshot(api_db_url)
    duplicate = await post(api_client, candidate)
    assert duplicate["status"] == "already_requested"
    assert duplicate["operation_id"] == first["operation_id"]
    other = await post(api_client, candidate, "different-key")
    assert other["status"] == "pilot_in_use"
    assert await snapshot(api_db_url) == before


async def test_concurrent_requests_and_delayed_worker(
    api_client: AsyncClient, api_db_url: str, candidate: str,
) -> None:
    results = await asyncio.gather(post(api_client, candidate), post(api_client, candidate))
    assert sum(item["status"] == "accepted" for item in results) == 1
    assert {item["status"] for item in results} <= {"accepted", "already_requested", "eligibility_unverified"}
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        assert not await claim_worker_generation(session, meeting_id=candidate,
                                                 generation=4, job_id="delayed", kind="transcription")
        assert not await claim_worker_generation(session, meeting_id=candidate,
                                                 generation=None, job_id="legacy", kind="transcription")
        assert len((await session.scalars(select(MeetingRecoveryOperation))).all()) == 1
        assert len((await session.scalars(select(MeetingRecoveryOutbox))).all()) == 1
    await engine.dispose()


async def test_worker_holding_fence_prevents_recovery(
    api_client: AsyncClient, api_db_url: str, candidate: str,
) -> None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    before = await snapshot(api_db_url)
    async with factory() as session, session.begin():
        await session.scalar(select(MeetingProcessingClaim).where(
            MeetingProcessingClaim.meeting_id == candidate).with_for_update())
        body = await asyncio.wait_for(post(api_client, candidate), timeout=5)
        assert body["status"] == "eligibility_unverified"
    assert await snapshot(api_db_url) == before
    await engine.dispose()


async def test_transaction_failure_rolls_back_gate_generation_history_and_outbox(
    api_client: AsyncClient, api_db_url: str, candidate: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = await snapshot(api_db_url)
    original = AsyncSession.flush

    async def fail_flush(self: AsyncSession, objects: object = None) -> None:
        await original(self)
        if any(isinstance(value, MeetingRecoveryOperation) for value in self.identity_map.values()):
            raise OperationalError("synthetic failure", {}, RuntimeError("synthetic"))

    monkeypatch.setattr(AsyncSession, "flush", fail_flush)
    body = await post(api_client, candidate)
    assert body["status"] == "eligibility_unverified"
    assert await snapshot(api_db_url) == before
