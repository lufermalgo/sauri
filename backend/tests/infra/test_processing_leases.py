"""Processing claims are leases: they expire unless renewed and a lapsed one can be taken over (#1166)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, MeetingProcessingClaim, StateHistory
from app.infra.processing_claims import (
    ClaimBusy,
    claim_worker_generation,
    heartbeat_seconds,
    lease_lapsed_at,
    lease_seconds,
    release_worker_claim,
    renew_claim,
    verify_worker_generation,
)

pytestmark = pytest.mark.asyncio


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, generation: int = 3, claim_id: str | None = None,
    claim_kind: str | None = None, expires_at: datetime | None = None, last_change: datetime | None = None,
) -> str:
    meeting_id = str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="transcribing", failure_cause=None,
            created_by=str(uuid.uuid4()), created_at=datetime.now(UTC),
        ))
        session.add(MeetingProcessingClaim(
            meeting_id=meeting_id, generation=generation, claim_id=claim_id, claim_kind=claim_kind,
            claim_expires_at=expires_at,
        ))
        if last_change is not None:
            session.add(StateHistory(
                id=str(uuid.uuid4()), meeting_id=meeting_id, state="transcribing", failure_cause=None,
                occurred_at=last_change,
            ))
    return meeting_id


async def _claim(
    factory: async_sessionmaker[AsyncSession], meeting_id: str, job_id: str, **extra: object,
) -> str | None:
    async with factory() as session, session.begin():
        return await claim_worker_generation(
            session, meeting_id=meeting_id, generation=3, job_id=job_id, kind="transcription", **extra,  # type: ignore[arg-type]
        )


async def _row(factory: async_sessionmaker[AsyncSession], meeting_id: str) -> MeetingProcessingClaim:
    async with factory() as session:
        row = await session.get(MeetingProcessingClaim, meeting_id)
        assert row is not None
        return row


def _aware(value: datetime | None) -> datetime:
    assert value is not None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def test_first_claim_holds_the_generation_under_its_job_id_with_a_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())

    assert await _claim(session_factory, meeting_id, job_id) == job_id

    row = await _row(session_factory, meeting_id)
    assert row.claim_id == job_id and row.claim_kind == "transcription"
    remaining = (_aware(row.claim_expires_at) - datetime.now(UTC)).total_seconds()
    assert 0 < remaining <= lease_seconds()


async def test_delivery_while_the_lease_is_live_is_deferred_not_dropped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = await _seed(session_factory)
    first = str(uuid.uuid4())
    assert await _claim(session_factory, meeting_id, first) == first

    with pytest.raises(ClaimBusy):
        await _claim(session_factory, meeting_id, str(uuid.uuid4()))
    with pytest.raises(ClaimBusy):  # the same message redelivered to a restarted worker, too
        await _claim(session_factory, meeting_id, first)

    assert (await _row(session_factory, meeting_id)).claim_id == first


async def test_lapsed_lease_is_taken_over_and_the_previous_holder_is_fenced_out(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dead = str(uuid.uuid4())
    meeting_id = await _seed(
        session_factory, claim_id=dead, claim_kind="transcription",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with session_factory() as session, session.begin():
        assert not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=3, job_id=dead, kind="transcription",
        )

    new_holder = await _claim(session_factory, meeting_id, dead)  # the redelivery of the very same message

    assert new_holder is not None and new_holder != dead
    row = await _row(session_factory, meeting_id)
    assert row.claim_id == new_holder and row.generation == 3
    assert _aware(row.claim_expires_at) > datetime.now(UTC)
    async with session_factory() as session, session.begin():
        # The old holder, even if it wakes up and still believes in its claim, can no longer commit.
        assert not await verify_worker_generation(
            session, meeting_id=meeting_id, generation=3, job_id=dead, kind="transcription", holder=dead,
        )
        assert await verify_worker_generation(
            session, meeting_id=meeting_id, generation=3, job_id=dead, kind="transcription", holder=new_holder,
        )


async def test_claim_without_expiry_is_lapsed_only_after_the_grace_since_the_last_state_change(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    legacy = str(uuid.uuid4())
    recent = await _seed(
        session_factory, claim_id=legacy, claim_kind="transcription",
        last_change=datetime.now(UTC) - timedelta(minutes=2),
    )
    old = await _seed(
        session_factory, claim_id=legacy, claim_kind="transcription",
        last_change=datetime.now(UTC) - timedelta(hours=3),
    )
    never = await _seed(session_factory, claim_id=legacy, claim_kind="transcription")

    with pytest.raises(ClaimBusy):
        await _claim(session_factory, recent, str(uuid.uuid4()))
    assert await _claim(session_factory, old, legacy) not in (None, legacy)
    assert await _claim(session_factory, never, legacy) not in (None, legacy)


async def test_reserved_recovery_claim_has_no_lease_and_is_not_takeable_by_ordinary_deliveries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    operation = str(uuid.uuid4())
    meeting_id = await _seed(session_factory, claim_id=operation, claim_kind="recovery")

    assert await _claim(session_factory, meeting_id, str(uuid.uuid4())) is None
    async with session_factory() as session:
        row = await session.get(MeetingProcessingClaim, meeting_id)
        assert row is not None and await lease_lapsed_at(session, row) is None


async def test_a_different_kind_of_claim_is_never_taken_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = await _seed(
        session_factory, claim_id=str(uuid.uuid4()), claim_kind="diarization",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert await _claim(session_factory, meeting_id, str(uuid.uuid4())) is None


async def test_renewal_extends_only_the_live_claim_of_its_holder(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())
    await _claim(session_factory, meeting_id, job_id)
    before = _aware((await _row(session_factory, meeting_id)).claim_expires_at)

    assert await renew_claim(
        session_factory, meeting_id=meeting_id, generation=3, holder=job_id, kind="transcription", lease_s=600,
    )
    assert _aware((await _row(session_factory, meeting_id)).claim_expires_at) > before + timedelta(minutes=5)
    assert not await renew_claim(
        session_factory, meeting_id=meeting_id, generation=3, holder="someone-else", kind="transcription", lease_s=600,
    )
    assert not await renew_claim(
        session_factory, meeting_id=meeting_id, generation=4, holder=job_id, kind="transcription", lease_s=600,
    )


async def test_renewal_after_the_lease_lapsed_does_not_revive_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    holder = str(uuid.uuid4())
    meeting_id = await _seed(
        session_factory, claim_id=holder, claim_kind="transcription",
        expires_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    assert not await renew_claim(
        session_factory, meeting_id=meeting_id, generation=3, holder=holder, kind="transcription", lease_s=600,
    )


async def test_release_frees_only_the_current_holders_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = await _seed(session_factory)
    job_id = str(uuid.uuid4())
    await _claim(session_factory, meeting_id, job_id)

    async with session_factory() as session, session.begin():
        assert not await release_worker_claim(
            session, meeting_id=meeting_id, generation=3, holder="stale", kind="transcription",
        )
    assert (await _row(session_factory, meeting_id)).claim_id == job_id
    async with session_factory() as session, session.begin():
        assert await release_worker_claim(
            session, meeting_id=meeting_id, generation=3, holder=job_id, kind="transcription",
        )
    row = await _row(session_factory, meeting_id)
    assert (row.claim_id, row.claim_kind, row.claim_expires_at) == (None, None, None)
    assert await _claim(session_factory, meeting_id, str(uuid.uuid4())) is not None


async def test_release_of_an_operation_run_goes_back_to_its_reserved_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    operation = str(uuid.uuid4())
    meeting_id = await _seed(session_factory, claim_id=operation, claim_kind="transcription",
                             expires_at=datetime.now(UTC) + timedelta(minutes=2))
    async with session_factory() as session, session.begin():
        assert await release_worker_claim(
            session, meeting_id=meeting_id, generation=3, holder=operation, kind="transcription",
            operation_id=operation,
        )
    row = await _row(session_factory, meeting_id)
    assert (row.claim_id, row.claim_kind, row.claim_expires_at) == (operation, "recovery", None)


async def test_lease_settings_are_validated_and_the_heartbeat_always_fits_in_the_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROCESSING_LEASE_SECONDS", "90")
    monkeypatch.setenv("PROCESSING_HEARTBEAT_SECONDS", "80")
    assert lease_seconds() == 90 and heartbeat_seconds() == 30  # at most a third of the lease
    monkeypatch.setenv("PROCESSING_LEASE_SECONDS", "-5")
    assert lease_seconds() == 150
    monkeypatch.setenv("PROCESSING_LEASE_SECONDS", "soon")
    assert lease_seconds() == 150
