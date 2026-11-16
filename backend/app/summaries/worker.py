"""Idempotent summary-event consumer with local engine at startup."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.engine_slot import (
    SLOT_WAIT_TIMEOUT_S,
    SUMMARY_ENGINE_CALL_TIMEOUT_S,
    EngineSlotTimeout,
    engine_slot,
)
from app.infra.models import Meeting, MeetingSummary, ProcessedSummaryEvent, SummaryRequestOutbox, Transcript
from app.infra.queue import JobQueue
from app.summaries.engine import ContextExceededError, SummaryProviderError
from app.summaries.factory import create_summarization_engine
from app.summaries.passages import SummaryInvalidError, encode_key_points
from app.summaries.repository import locked_request, transcript_passages

logger = logging.getLogger(__name__)

# Hard limit for one engine call; module-level so tests can shrink it.
ENGINE_CALL_TIMEOUT_S = SUMMARY_ENGINE_CALL_TIMEOUT_S


def _event_id(message: dict[str, Any]) -> str | None:
    value = message.get("event_id")
    return value if isinstance(value, str) and value.strip() else None


def _matches_request(message: dict[str, Any], request: SummaryRequestOutbox) -> bool:
    return all(
        message.get(key) == getattr(request, key)
        for key in (
            "meeting_id",
            "transcript_id",
            "generation",
            "template_id",
            "template_version",
            "instructions_snapshot",
        )
    )


async def start_worker(queue: JobQueue, factory: async_sessionmaker[AsyncSession]) -> None:
    """Register the normal consumer and terminal dead-letter status handler."""
    engine = create_summarization_engine()

    async def record_failure(message: dict[str, Any], cause: str, *, terminal: bool) -> None:
        async with factory() as session, session.begin():
            request = await locked_request(session, message["event_id"])
            if request is None or not _matches_request(message, request):
                return
            if request.status in ("succeeded", "failed"):
                return
            if await session.get(ProcessedSummaryEvent, request.event_id) is not None:
                return
            request.failure_cause = cause
            if terminal:
                request.status = "failed"
                request.finished_at = datetime.now(UTC)

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
            passages = await transcript_passages(session, request.transcript_id)
            instructions = request.instructions_snapshot
            if instructions is None:
                raise ValueError("Accepted summary request has no instruction snapshot")
            request.status = "running"
            if request.started_at is None:  # Redeliveries and retries keep the first attempt's time.
                request.started_at = datetime.now(UTC)

        # Only provider availability/timeouts are retryable generation failures.
        # Acknowledge deterministic failures after persisting a terminal outcome.
        try:
            async with engine_slot(factory.kw["bind"], kind="summary", timeout_s=SLOT_WAIT_TIMEOUT_S):
                async with asyncio.timeout(ENGINE_CALL_TIMEOUT_S):
                    result = await engine.generate(passages, instructions)
        except EngineSlotTimeout:
            raise
        except ContextExceededError:
            await record_failure(message, "context_exceeded", terminal=True)
            return
        except SummaryInvalidError:
            await record_failure(message, "summary_invalid", terminal=True)
            return
        except (SummaryProviderError, TimeoutError):
            await record_failure(message, "llm_unavailable", terminal=False)
            raise
        except Exception:
            await record_failure(message, "summary_invalid", terminal=True)
            return

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
            session.add(
                MeetingSummary(
                    id=str(uuid4()),
                    event_id=event_id,
                    meeting_id=request.meeting_id,
                    transcript_id=request.transcript_id,
                    template_id=request.template_id,
                    template_version=request.template_version,
                    generation=request.generation,
                    topic=result.topic,
                    key_points_json=encode_key_points(result),
                    created_at=now,
                    updated_at=now,
                )
            )
            request.status = "succeeded"
            request.failure_cause = None
            request.finished_at = now

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
                request.failure_cause = "llm_unavailable"
                request.finished_at = datetime.now(UTC)

    await queue.subscribe("summarize", consume)
    await queue.subscribe("summarize.failed", terminal)
