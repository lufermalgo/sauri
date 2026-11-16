"""The heartbeat keeps a claim alive during one long call; an interrupted delivery gives it back (#1166)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.claim_lease import ClaimLost, LeaseScope
from app.infra.models import Meeting, MeetingProcessingClaim
from app.infra.processing_claims import claim_worker_generation, verify_worker_generation

pytestmark = pytest.mark.asyncio


async def _claimed(factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    meeting_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="transcribing", failure_cause=None,
            created_by=str(uuid.uuid4()), created_at=datetime.now(UTC),
        ))
        session.add(MeetingProcessingClaim(meeting_id=meeting_id, generation=1))
    async with factory() as session, session.begin():
        holder = await claim_worker_generation(
            session, meeting_id=meeting_id, generation=1, job_id=job_id, kind="transcription",
        )
    assert holder == job_id
    return meeting_id, job_id


async def _row(factory: async_sessionmaker[AsyncSession], meeting_id: str) -> MeetingProcessingClaim:
    async with factory() as session:
        row = await session.get(MeetingProcessingClaim, meeting_id)
        assert row is not None
        return row


def _scope(factory: async_sessionmaker[AsyncSession], lease_s: float = 0.4, heartbeat_s: float = 0.05) -> LeaseScope:
    return LeaseScope(factory, lease_s=lease_s, heartbeat_s=heartbeat_s)


async def test_one_call_longer_than_the_lease_keeps_its_claim_alive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    async with _scope(session_factory) as scope:
        scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
        await scope.guard(asyncio.sleep(1.0))  # 2.5 leases, no chunk boundary to renew between
        async with session_factory() as session, session.begin():
            assert await verify_worker_generation(
                session, meeting_id=meeting_id, generation=1, job_id=job_id, kind="transcription",
            )
        assert not scope.lost


async def test_without_the_heartbeat_the_same_call_would_lose_its_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    async with session_factory() as session, session.begin():
        row = await session.get(MeetingProcessingClaim, meeting_id)
        assert row is not None
        row.claim_expires_at = datetime.now(UTC) + timedelta(seconds=0.3)
    await asyncio.sleep(0.5)
    async with session_factory() as session, session.begin():
        assert not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=1, job_id=job_id, kind="transcription",
        )


async def test_losing_the_claim_aborts_the_running_call(session_factory: async_sessionmaker[AsyncSession]) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    cancelled = asyncio.Event()

    async def engine_call() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with _scope(session_factory) as scope:
        scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
        async with session_factory() as session, session.begin():  # another worker took the claim over
            row = await session.get(MeetingProcessingClaim, meeting_id)
            assert row is not None
            row.claim_id = str(uuid.uuid4())
        with pytest.raises(ClaimLost):
            await scope.guard(engine_call())
    assert cancelled.is_set() and scope.lost


async def test_a_database_outage_longer_than_the_lease_counts_as_lost(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id, job_id = await _claimed(session_factory)

    async def broken(*args: object, **kwargs: object) -> bool:
        raise ConnectionError("database unreachable")

    monkeypatch.setattr("app.infra.claim_lease.renew_claim", broken)
    async with _scope(session_factory, lease_s=0.3) as scope:
        scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
        with pytest.raises(ClaimLost):
            await scope.guard(asyncio.sleep(30))


async def test_an_interrupted_delivery_releases_its_claim_for_the_redelivery(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    with pytest.raises(RuntimeError):
        async with _scope(session_factory) as scope:
            scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
            raise RuntimeError("worker handler failed")

    row = await _row(session_factory, meeting_id)
    assert (row.claim_id, row.claim_kind, row.claim_expires_at) == (None, None, None)
    async with session_factory() as session, session.begin():  # the redelivery claims at once, no waiting
        assert await claim_worker_generation(
            session, meeting_id=meeting_id, generation=1, job_id=job_id, kind="transcription",
        ) == job_id


async def test_a_cancelled_delivery_releases_its_claim(session_factory: async_sessionmaker[AsyncSession]) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    started = asyncio.Event()

    async def delivery() -> None:
        async with _scope(session_factory) as scope:
            scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
            started.set()
            await scope.guard(asyncio.sleep(30))

    task = asyncio.create_task(delivery())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _row(session_factory, meeting_id)).claim_id is None


async def test_a_finished_delivery_keeps_its_claim_and_stops_renewing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    async with _scope(session_factory) as scope:
        scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
    row = await _row(session_factory, meeting_id)
    assert row.claim_id == job_id  # the claim records that this generation was consumed
    expires = row.claim_expires_at
    await asyncio.sleep(0.2)
    assert (await _row(session_factory, meeting_id)).claim_expires_at == expires


async def test_a_lost_claim_is_not_released_over_the_new_holder(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, job_id = await _claimed(session_factory)
    other = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        async with _scope(session_factory) as scope:
            scope.arm(meeting_id=meeting_id, generation=1, holder=job_id, kind="transcription")
            async with session_factory() as session, session.begin():
                row = await session.get(MeetingProcessingClaim, meeting_id)
                assert row is not None
                row.claim_id = other
            raise RuntimeError("late failure of the old holder")
    assert (await _row(session_factory, meeting_id)).claim_id == other


async def test_untracked_work_has_nothing_to_renew(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with _scope(session_factory) as scope:
        scope.arm(meeting_id="m", generation=1, holder="untracked", kind="transcription")
        assert await scope.guard(asyncio.sleep(0.05, result="done")) == "done"
