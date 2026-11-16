"""Idempotent summary-event consumer with local engine at startup."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.engines.repository import apply_provenance
from app.engines.routing import ProviderError, Route, call_with_fallback, resolve_route
from app.infra.engine_slot import (
    SLOT_WAIT_TIMEOUT_S,
    SUMMARY_ENGINE_CALL_TIMEOUT_S,
    EngineSlotTimeout,
    engine_slot,
)
from app.infra.models import Meeting, MeetingSummary, ProcessedSummaryEvent, SummaryRequestOutbox, Transcript
from app.infra.queue import JobQueue
from app.regeneration.service import settle_summary_operations
from app.summaries.engine import ContextExceededError, SummaryAnswer, SummaryProviderError
from app.summaries.factory import create_summarization_engine
from app.summaries.passages import SummaryInvalidError, encode_key_points
from app.summaries.repository import locked_request, transcript_passages

logger = logging.getLogger(__name__)

# Hard limit for one engine call; module-level so tests can shrink it.
ENGINE_CALL_TIMEOUT_S = SUMMARY_ENGINE_CALL_TIMEOUT_S


def _event_id(message: dict[str, Any]) -> str | None:
    value = message.get("event_id")
    return value if isinstance(value, str) and value.strip() else None


def _engine_names(answer: SummaryAnswer) -> tuple[str | None, str | None]:
    """What the engine reported about itself, for the provenance recorded on the summary."""
    return answer.engine_name, answer.engine_model


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
                await session.flush()
                await settle_summary_operations(session, request.event_id)

    async def provider_failure(message: dict[str, Any], error: ProviderError) -> None:
        """Store the classified cause. A transient class is retried through the queue (its attempts are bounded
        by SUMMARIZE_MAX_RETRIES); every other class, quota included, ends this request and keeps its cause."""
        transient = error.retryable and error.code != "provider_quota"
        await record_failure(message, error.code, terminal=not transient)
        if transient:
            raise SummaryProviderError(error.code) from None

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
                logger.info("Summary delivery dropped; reason=stage_complete")
                return
            meeting = await session.get(Meeting, request.meeting_id)
            transcript = await session.get(Transcript, request.transcript_id)
            if meeting is None or transcript is None or transcript.meeting_id != request.meeting_id:
                logger.warning("Summary meeting or transcript unavailable for event_id=%s", event_id)
                return
            passages = await transcript_passages(session, request.transcript_id)
            owner_id = meeting.created_by
            instructions = request.instructions_snapshot
            if instructions is None:
                raise ValueError("Accepted summary request has no instruction snapshot")
            request.status = "running"
            if request.started_at is None:  # Redeliveries and retries keep the first attempt's time.
                request.started_at = datetime.now(UTC)

        # Read on every attempt, so a change in Settings applies to the next one without restarting anything.
        # Without a setting the route is None: the default local engine, exactly as before engines were selectable.
        # A missing consent fails here, before anything is sent anywhere.
        try:
            async with factory() as session:
                resolved = await resolve_route(session, owner_id, "summary")
        except ProviderError as error:
            await provider_failure(message, error)
            return

        async def attempt(route: Route | None) -> SummaryAnswer:
            return await engine.generate(passages, instructions, route)

        # Only provider availability/timeouts are retryable generation failures.
        # Acknowledge deterministic failures after persisting a terminal outcome.
        try:
            async with engine_slot(factory.kw["bind"], kind="summary", timeout_s=SLOT_WAIT_TIMEOUT_S):
                async with asyncio.timeout(ENGINE_CALL_TIMEOUT_S):
                    answer, provenance = await call_with_fallback(resolved, attempt, _engine_names)
        except EngineSlotTimeout:
            raise
        except ProviderError as error:
            await provider_failure(message, error)
            return
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
            summary = MeetingSummary(
                id=str(uuid4()),
                event_id=event_id,
                meeting_id=request.meeting_id,
                transcript_id=request.transcript_id,
                template_id=request.template_id,
                template_version=request.template_version,
                generation=request.generation,
                topic=answer.summary.topic,
                key_points_json=encode_key_points(answer.summary),
                created_at=now,
                updated_at=now,
            )
            apply_provenance(summary, provenance)
            session.add(summary)
            logger.info(
                "Summary produced; engine=%s external=%s fallback_reason=%s",
                provenance.engine_name, provenance.external, provenance.fallback_reason,
            )
            request.status = "succeeded"
            request.failure_cause = None
            request.finished_at = now
            await session.flush()
            await settle_summary_operations(session, event_id)

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
                request.failure_cause = request.failure_cause or "llm_unavailable"
                request.finished_at = datetime.now(UTC)
                await session.flush()
                await settle_summary_operations(session, event_id)

    await queue.subscribe("summarize", consume)
    await queue.subscribe("summarize.failed", terminal)
