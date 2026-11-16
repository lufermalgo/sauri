"""#1045: worker timestamps and the stale-request sweeper, on disposable PostgreSQL."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.infra.models import MeetingSummary, ProcessedSummaryEvent, SummaryRequestOutbox
from app.summaries.sweeper import DEFAULT_STALE_AFTER_SECONDS, STALE_CAUSE, fail_stale_requests, stale_after_seconds
from tests.summaries.test_worker import Case, outcomes, registered

pytest_plugins = ("tests.summaries.test_worker",)  # shared disposable PG fixture



@pytest.fixture(autouse=True)
def require_disposable_postgres() -> None:
    # Runs before the shared `case` fixture, which fails hard without the disposable database.
    if not os.environ.get("SAURI_QA_POSTGRES_URL"):
        pytest.skip("SAURI_QA_POSTGRES_URL required (disposable sauri_t11_* PostgreSQL)")


NOW = datetime.now(UTC)
OLD = NOW - timedelta(hours=3)
RECENT = NOW - timedelta(minutes=5)
LIMIT = timedelta(minutes=75)


async def request_row(case: Case, event_id: str) -> SummaryRequestOutbox:
    async with case.factory() as session:
        row = await session.get(SummaryRequestOutbox, event_id)
        assert row is not None
        return row


async def add_request(
    case: Case, generation: int, status: str, *, delivered_at: datetime | None, started_at: datetime | None = None,
    with_summary: bool = False,
) -> str:
    event_id = str(uuid4())
    base = case.message
    async with case.factory() as session, session.begin():
        session.add(SummaryRequestOutbox(
            event_id=event_id, meeting_id=base["meeting_id"], transcript_id=base["transcript_id"],
            template_id=base["template_id"], template_version=1, instructions_snapshot=base["instructions_snapshot"],
            generation=generation, status=status, delivered_at=delivered_at, started_at=started_at,
        ))
        if with_summary:
            await session.flush()
            session.add(ProcessedSummaryEvent(event_id=event_id, meeting_id=base["meeting_id"], completed_at=NOW))
            session.add(MeetingSummary(
                id=str(uuid4()), event_id=event_id, meeting_id=base["meeting_id"],
                transcript_id=base["transcript_id"], template_id=base["template_id"], template_version=1,
                generation=generation, topic="Synthetic", key_points_json="[]", created_at=NOW, updated_at=NOW,
            ))
    return event_id


async def test_worker_records_first_start_and_finish(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = await registered(case, monkeypatch)
    event_id = case.message["event_id"]
    assert (await request_row(case, event_id)).started_at is None
    case.failure = True
    with pytest.raises(Exception, match="llm_unavailable"):
        await queue.handlers["summarize"](case.message.copy())
    first = await request_row(case, event_id)
    assert first.status == "running" and first.started_at is not None and first.finished_at is None
    case.failure = False
    await queue.handlers["summarize"](case.message.copy())  # the broker retry
    done = await request_row(case, event_id)
    assert done.status == "succeeded"
    assert done.started_at == first.started_at  # the retry never moves the start
    assert done.finished_at is not None and done.finished_at >= done.started_at


async def test_worker_terminal_failure_records_finish(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.summaries.passages import SummaryInvalidError

    async def invalid(*_: object) -> None:
        raise SummaryInvalidError("summary_invalid")

    monkeypatch.setattr(case, "generate", invalid)
    queue = await registered(case, monkeypatch)
    await queue.handlers["summarize"](case.message.copy())
    row = await request_row(case, case.message["event_id"])
    assert (row.status, row.failure_cause) == ("failed", "summary_invalid")
    assert row.started_at is not None and row.finished_at is not None


async def test_sweeper_fails_only_old_unsettled_delivered_requests(case: Case) -> None:
    old_running = await add_request(case, 2, "running", delivered_at=OLD, started_at=OLD)
    legacy_running = await add_request(case, 3, "running", delivered_at=OLD)  # no started_at: delivery time counts
    lost_pending = await add_request(case, 4, "pending", delivered_at=OLD)
    recent_running = await add_request(case, 5, "running", delivered_at=OLD, started_at=RECENT)
    recent_pending = await add_request(case, 6, "pending", delivered_at=RECENT)
    undelivered = await add_request(case, 7, "pending", delivered_at=None)  # the outbox still owns this one
    failed = await add_request(case, 8, "failed", delivered_at=OLD, started_at=OLD)
    succeeded = await add_request(case, 9, "succeeded", delivered_at=OLD, started_at=OLD, with_summary=True)
    # A stored summary protects the request even if its status is inconsistent.
    summarized = await add_request(case, 10, "running", delivered_at=OLD, started_at=OLD, with_summary=True)
    seeded = case.message["event_id"]  # pending, delivered a moment ago

    assert await fail_stale_requests(case.factory, stale_after=LIMIT) == 3
    status = {event: (await request_row(case, event)).status for event in (
        old_running, legacy_running, lost_pending, recent_running, recent_pending, undelivered,
        failed, succeeded, summarized, seeded,
    )}
    assert [status[e] for e in (old_running, legacy_running, lost_pending)] == ["failed"] * 3
    assert status[recent_running] == "running" and status[recent_pending] == "pending"
    assert status[undelivered] == "pending" and status[seeded] == "pending"
    assert status[failed] == "failed" and status[succeeded] == "succeeded" and status[summarized] == "running"
    for event in (old_running, legacy_running, lost_pending):
        row = await request_row(case, event)
        assert row.failure_cause == STALE_CAUSE and row.finished_at is not None
    assert (await request_row(case, failed)).failure_cause is None  # untouched
    assert (await request_row(case, succeeded)).finished_at is None

    # Idempotent: a second pass finds nothing and rewrites nothing.
    before = (await request_row(case, old_running)).finished_at
    assert await fail_stale_requests(case.factory, stale_after=LIMIT) == 0
    assert (await request_row(case, old_running)).finished_at == before


async def test_redelivery_of_a_swept_request_is_a_noop(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    event_id = case.message["event_id"]
    async with case.factory() as session, session.begin():
        row = await session.get(SummaryRequestOutbox, event_id)
        assert row is not None
        row.status, row.started_at, row.delivered_at = "running", OLD, OLD
    assert await fail_stale_requests(case.factory, stale_after=LIMIT) == 1
    queue = await registered(case, monkeypatch)
    await queue.handlers["summarize"](case.message.copy())
    assert case.engine_calls == []
    status, summaries, processed = await outcomes(case)
    assert (status, summaries, processed) == ("failed", [], False)
    async with case.factory() as session:
        assert (await session.scalars(select(SummaryRequestOutbox.failure_cause))).one() == STALE_CAUSE


def test_stale_limit_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUMMARY_STALE_AFTER_SECONDS", raising=False)
    assert stale_after_seconds() == DEFAULT_STALE_AFTER_SECONDS == 75 * 60
    for raw, expected in (("600", 600), (" 90 ", 90), ("0", 4500), ("-5", 4500), ("abc", 4500), ("", 4500)):
        monkeypatch.setenv("SUMMARY_STALE_AFTER_SECONDS", raw)
        assert stale_after_seconds() == expected
