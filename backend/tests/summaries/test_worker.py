"""T11/#279 RED — registered summary consumer, real PostgreSQL outcomes.

Synthetic queue/engine are contract test doubles, not evidence of broker/provider
execution. Use an exclusively disposable database named sauri_t11_*.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.database import Base
from app.infra.models import (
    Meeting,
    MeetingSummary,
    ProcessedSummaryEvent,
    SpeechTurn,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
    User,
)
from app.infra.queue import JobQueue

Handler = Callable[[dict[str, Any]], Awaitable[None]]
Factory = async_sessionmaker[AsyncSession]


@dataclass
class CapturedQueue(JobQueue):
    """Exercise handlers actually registered at startup, never private helpers."""

    handlers: dict[str, Handler] = field(default_factory=dict)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        pytest.fail("Summary consumer must not publish downstream jobs")

    async def subscribe(self, topic: str, handler: Handler) -> None:
        self.handlers[topic] = handler


@dataclass
class Case:
    factory: Factory
    message: dict[str, Any]
    owner: str
    engine_calls: list[tuple[str, str]] = field(default_factory=list)
    failure: bool = False

    async def generate(self, transcript_text: str, instructions_snapshot: str) -> SimpleNamespace:
        # Read through a separate connection: running must be durable before generation.
        async with self.factory() as session:
            request = await session.get(SummaryRequestOutbox, self.message["event_id"])
            assert request is not None and request.status == "running"
        self.engine_calls.append((transcript_text, instructions_snapshot))
        if self.failure:
            raise RuntimeError("synthetic retryable provider error, not for status output")
        return SimpleNamespace(topic="Synthetic topic", key_points=["Synthetic key point"])


@pytest.fixture
async def case() -> AsyncIterator[Case]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.fail("Set SAURI_QA_POSTGRES_URL to an exclusively disposable sauri_t11_* PostgreSQL database")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg" or not re.fullmatch(r"sauri_t11_[a-zA-Z0-9_]+", url.database or ""):
        pytest.fail("Refusing database outside the dedicated sauri_t11_* namespace")
    engine = create_async_engine(url)
    schema = f"t11_{uuid4().hex}"
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await engine.dispose()
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner, meeting, transcript, template, event_id = (str(uuid4()) for _ in range(5))
        now = datetime.now(UTC)
        message: dict[str, Any] = dict(
            event_id=event_id,
            meeting_id=meeting,
            transcript_id=transcript,
            generation=1,
            template_id=template,
            template_version=1,
            instructions_snapshot="  Frozen opaque instructions.\n",
        )
        async with factory() as session, session.begin():
            session.add(
                User(
                    id=owner,
                    email=f"{owner}@example.test",
                    name="Synthetic",
                    password_hash="test-only",
                    is_sales=True,
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                Meeting(
                    id=meeting,
                    meet_link=None,
                    origin="upload",
                    process_state="completed",
                    created_by=owner,
                    created_at=now,
                )
            )
            await session.flush()
            session.add_all(
                [
                    Transcript(
                        id=transcript,
                        meeting_id=meeting,
                        language="es-CO",
                        provider="synthetic",
                        supports_turns=False,
                        created_at=now,
                    ),
                    SummaryTemplate(
                        id=template,
                        owner_user_id=owner,
                        name="Synthetic",
                        instructions=message["instructions_snapshot"],
                        version=1,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add(
                SpeechTurn(
                    id=str(uuid4()),
                    transcript_id=transcript,
                    text="Synthetic transcript.",
                    start_ms=0,
                    end_ms=1000,
                    sequence=1,
                )
            )
            session.add(SummaryRequestOutbox(**message, status="pending", delivered_at=now))
        yield Case(factory, message, owner)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def registered(case: Case, monkeypatch: pytest.MonkeyPatch) -> CapturedQueue:
    try:
        worker = importlib.import_module("app.summaries.worker")
    except ModuleNotFoundError as error:
        if error.name not in {"app.summaries", "app.summaries.worker"}:
            raise
        pytest.fail("T11 RED: summary consumer app.summaries.worker is absent")
    monkeypatch.setattr(worker, "create_summarization_engine", lambda: case, raising=False)
    queue = CapturedQueue()
    await worker.start_worker(queue, case.factory)
    assert "summarize" in queue.handlers, "start_worker must register the summarize consumer"
    return queue


async def outcomes(case: Case, event_id: str | None = None) -> tuple[str, list[MeetingSummary], bool]:
    event_id = event_id or case.message["event_id"]
    async with case.factory() as session:
        request = await session.get(SummaryRequestOutbox, event_id)
        assert request is not None
        summaries = list(await session.scalars(select(MeetingSummary).where(MeetingSummary.event_id == event_id)))
        processed = await session.get(ProcessedSummaryEvent, event_id)
        return request.status, summaries, processed is not None


async def test_snapshot_survives_template_edit_and_default_change(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    replacement = str(uuid4())
    async with case.factory() as session, session.begin():
        template = await session.get(SummaryTemplate, case.message["template_id"])
        assert template is not None
        template.instructions, template.version = "Edited instructions", 2
        now = datetime.now(UTC)
        session.add(
            SummaryTemplate(
                id=replacement,
                owner_user_id=case.owner,
                name="Later default",
                version=1,
                instructions="Replacement instructions",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        user = await session.get(User, case.owner)
        assert user is not None
        user.default_summary_template_id = replacement
    queue = await registered(case, monkeypatch)
    await queue.handlers["summarize"](case.message.copy())
    assert case.engine_calls == [("Synthetic transcript.", case.message["instructions_snapshot"])]
    status, rows, processed = await outcomes(case)
    assert status == "succeeded" and processed and len(rows) == 1
    assert (rows[0].template_id, rows[0].template_version, rows[0].generation) == (case.message["template_id"], 1, 1)
    assert (rows[0].topic, json.loads(rows[0].key_points_json)) == ("Synthetic topic", ["Synthetic key point"])
    async with case.factory() as session:
        meeting = await session.get(Meeting, case.message["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"


async def test_committed_duplicate_is_noop_without_regeneration(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = await registered(case, monkeypatch)
    await queue.handlers["summarize"](case.message.copy())
    _, before, _ = await outcomes(case)
    assert len(before) == 1
    case.failure = True  # Any attempted regeneration must fail the test.
    await queue.handlers["summarize"](case.message.copy())
    status, after, processed = await outcomes(case)
    assert status == "succeeded" and processed and len(after) == 1
    assert (after[0].id, after[0].topic, after[0].key_points_json) == (
        before[0].id,
        before[0].topic,
        before[0].key_points_json,
    )
    assert len(case.engine_calls) == 1


async def test_concurrent_redelivery_commits_one_outcome(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = await registered(case, monkeypatch)
    await asyncio.gather(*(queue.handlers["summarize"](case.message.copy()) for _ in range(2)))
    status, rows, processed = await outcomes(case)
    assert status == "succeeded" and processed and len(rows) == 1


async def test_retryable_error_leaves_no_claim_or_artifact_and_can_retry(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await registered(case, monkeypatch)
    case.failure = True
    with pytest.raises(RuntimeError, match="synthetic retryable"):
        await queue.handlers["summarize"](case.message.copy())
    status, rows, processed = await outcomes(case)
    assert status == "running" and rows == [] and not processed
    case.failure = False
    await queue.handlers["summarize"](case.message.copy())
    status, rows, processed = await outcomes(case)
    assert status == "succeeded" and len(rows) == 1 and processed


async def test_persistence_failure_rolls_back_summary_claim_and_success(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await registered(case, monkeypatch)
    # Fail the request's success write in PostgreSQL, independently of ORM write order.
    async with case.factory() as session, session.begin():
        await session.execute(
            text("""
            CREATE FUNCTION reject_success() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.status = 'succeeded' THEN RAISE EXCEPTION 't11 atomic fault'; END IF;
                RETURN NEW;
            END $$
        """)
        )
        await session.execute(
            text("""
            CREATE TRIGGER t11_reject_success BEFORE UPDATE ON summary_request_outbox
            FOR EACH ROW EXECUTE FUNCTION reject_success()
        """)
        )
    with pytest.raises(Exception, match="t11 atomic fault"):
        await queue.handlers["summarize"](case.message.copy())
    status, rows, processed = await outcomes(case)
    assert status == "running" and rows == [] and not processed
    async with case.factory() as session, session.begin():
        await session.execute(text("DROP TRIGGER t11_reject_success ON summary_request_outbox"))
    await queue.handlers["summarize"](case.message.copy())
    status, rows, processed = await outcomes(case)
    assert status == "succeeded" and len(rows) == 1 and processed


async def test_terminal_dead_letter_preserves_earlier_success(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = await registered(case, monkeypatch)
    await queue.handlers["summarize"](case.message.copy())
    _, original, _ = await outcomes(case)
    later = {**case.message, "event_id": str(uuid4()), "generation": 2}
    async with case.factory() as session, session.begin():
        session.add(SummaryRequestOutbox(**later, status="running", delivered_at=datetime.now(UTC)))
    # The queue interface has no exhaustion callback: capture the terminal consumer
    # registered by this worker. Its DLQ topic name is deliberately not prescribed.
    terminal = [handler for topic, handler in queue.handlers.items() if topic != "summarize"]
    assert len(terminal) == 1, "Startup must wire a terminal dead-letter handler, not just a private helper"
    await terminal[0](later)
    await terminal[0](later)  # Terminal redelivery must be safe too.
    status, rows, processed = await outcomes(case, later["event_id"])
    assert status == "failed" and rows == [] and not processed
    old_status, surviving, old_processed = await outcomes(case)
    assert old_status == "succeeded" and old_processed and len(surviving) == 1
    assert surviving[0].id == original[0].id
    assert len(case.engine_calls) == 1
