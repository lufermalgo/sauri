"""Idempotent summary-event consumer; provider construction is deferred to T14."""

from __future__ import annotations

import importlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, MeetingSummary, ProcessedSummaryEvent, SummaryRequestOutbox, Transcript
from app.infra.queue import JobQueue
from app.summaries.repository import locked_request, transcript_text

logger = logging.getLogger(__name__)


class SummaryResult(Protocol):
    topic: str
    key_points: list[str]


class SummarizationEngine(Protocol):
    async def generate(self, transcript_text: str, instructions_snapshot: str) -> SummaryResult: ...


def create_summarization_engine() -> SummarizationEngine:
    """T14 supplies the local engine; until then startup must fail closed."""
    try:
        module = importlib.import_module("app.summaries.factory")
    except ModuleNotFoundError as exc:
        if exc.name != "app.summaries.factory":
            raise
        raise RuntimeError("Summary engine is not configured; T14 local adapter is required") from exc
    factory = module.create_summarization_engine
    engine: SummarizationEngine = factory()
    return engine


def _event_id(message: dict[str, Any]) -> str | None:
    value = message.get("event_id")
    return value if isinstance(value, str) and value.strip() else None


def _matches_request(message: dict[str, Any], request: SummaryRequestOutbox) -> bool:
    return all(message.get(key) == getattr(request, key) for key in (
        "meeting_id", "transcript_id", "generation", "template_id", "template_version", "instructions_snapshot",
    ))


async def start_worker(queue: JobQueue, factory: async_sessionmaker[AsyncSession]) -> None:
    """Register the normal consumer and terminal dead-letter status handler."""
    engine = create_summarization_engine()

    async def consume(message: dict[str, Any]) -> None:
        meeting_id = message.get("meeting_id")
        event_id = _event_id(message)
        if not isinstance(meeting_id, str) or not meeting_id.strip() or event_id is None:
            logger.warning("Summary message discarded: missing meeting_id or event_id")
            return

        # This commit makes running visible outside the generation transaction.
        async with factory() as session, session.begin():
            request = await locked_request(session, event_id)
            if request is None:
                logger.warning("Summary request not found for event_id=%s", event_id)
                return
            if not _matches_request(message, request):
                raise ValueError("Summary event does not match the accepted request")
            processed = await session.get(ProcessedSummaryEvent, event_id)
            if processed is not None or request.status in ("succeeded", "failed"):
                return
            meeting = await session.get(Meeting, request.meeting_id)
            transcript = await session.get(Transcript, request.transcript_id)
            if meeting is None or transcript is None or transcript.meeting_id != request.meeting_id:
                logger.warning("Summary meeting or transcript unavailable for event_id=%s", event_id)
                return
            text = await transcript_text(session, request.transcript_id)
            instructions = request.instructions_snapshot
            request.status = "running"

        # No DB transaction remains open during provider work. A failure propagates
        # for the queue's retry policy; neither artifact nor event claim is written.
        result = await engine.generate(text, instructions)

        async with factory() as session, session.begin():
            request = await locked_request(session, event_id)
            if request is None or await session.get(ProcessedSummaryEvent, event_id) is not None:
                return
            if request.status in ("succeeded", "failed"):
                return
            if not _matches_request(message, request):
                raise ValueError("Summary event changed after generation")
            now = datetime.now(UTC)
            session.add(ProcessedSummaryEvent(event_id=event_id, meeting_id=request.meeting_id, completed_at=now))
            session.add(MeetingSummary(
                id=str(uuid4()), event_id=event_id, meeting_id=request.meeting_id,
                transcript_id=request.transcript_id, template_id=request.template_id,
                template_version=request.template_version, generation=request.generation,
                topic=result.topic, key_points_json=json.dumps(result.key_points, ensure_ascii=False),
                created_at=now, updated_at=now,
            ))
            request.status = "succeeded"

    async def terminal(message: dict[str, Any]) -> None:
        event_id = _event_id(message)
        if event_id is None:
            logger.warning("Summary dead-letter discarded: missing event_id")
            return
        async with factory() as session, session.begin():
            request = await locked_request(session, event_id)
            if request is None or not _matches_request(message, request):
                logger.warning("Summary dead-letter does not match accepted event_id=%s", event_id)
                return
            processed = await session.get(ProcessedSummaryEvent, event_id)
            if processed is None and request.status not in ("succeeded", "failed"):
                request.status = "failed"

    await queue.subscribe("summarize", consume)
    await queue.subscribe("summarize.failed", terminal)
