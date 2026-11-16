"""Atomic, owner-scoped acceptance of an immutable summary request."""

import logging
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SummaryRequestOutbox, SummaryTemplate, User
from app.summaries import repository

logger = logging.getLogger(__name__)


async def accept_request(
    session: AsyncSession, meeting_id: str, owner_id: str, template_id: str | None,
    *, processing_revision: int | None = None,
) -> SummaryRequestOutbox:
    meeting = await repository.owned_meeting_locked(session, meeting_id, owner_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Stable identity under the meeting lock survives redelivery and template edits.
    event_id = str(uuid4())
    if processing_revision is not None:
        event_id = str(uuid5(NAMESPACE_URL, f"sauri:auto-summary:{meeting_id}:{processing_revision}"))
        existing = await session.get(SummaryRequestOutbox, event_id)
        if existing is not None:
            return existing
    transcript = await repository.transcript_for_meeting(session, meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    if processing_revision is not None:
        # Automatic requests exist only for the first summary of a transcript. Once any
        # request or summary exists, a new summary needs an explicit user request.
        prior = await repository.latest_request(session, transcript.id)
        if prior is not None:
            logger.info("Automatic summary request skipped; reason=summary_already_requested")
            return prior
    if processing_revision is None:
        # Repeated clicks, a second tab or a retried request converge on the work in flight.
        active = await repository.active_request(session, transcript.id)
        if active is not None:
            return active
    template = await repository.selected_template(session, owner_id, template_id)
    if template is None:
        if template_id is None:
            raise HTTPException(status_code=503, detail="Default summary template unavailable")
        raise HTTPException(status_code=422, detail="Invalid template_id")
    row = SummaryRequestOutbox(
        event_id=event_id, meeting_id=meeting_id, transcript_id=transcript.id,
        template_id=template.id, template_version=template.version,
        instructions_snapshot=template.instructions,
        generation=await repository.next_generation(session, transcript.id), status="pending",
        delivered_at=None, requested_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def record_failed_request(
    session: AsyncSession, meeting_id: str, owner_id: str, processing_revision: int,
) -> SummaryRequestOutbox:
    """Persist acceptance failure separately; never replace an already accepted event."""
    if await repository.owned_meeting_locked(session, meeting_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    event_id = str(uuid5(NAMESPACE_URL, f"sauri:auto-summary:{meeting_id}:{processing_revision}"))
    existing = await session.get(SummaryRequestOutbox, event_id)
    if existing is not None:
        return existing
    transcript = await repository.transcript_for_meeting(session, meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    prior = await repository.latest_request(session, transcript.id)
    if prior is not None:
        return prior  # A request already exists; a failed automatic attempt must not add another.
    now = datetime.now(UTC)
    # Read only the configured owned snapshot, without repeating default seeding
    # or changing the owner's preference after acceptance has already failed.
    template = await session.scalar(select(SummaryTemplate).join(
        User, User.default_summary_template_id == SummaryTemplate.id,
    ).where(User.id == owner_id, SummaryTemplate.owner_user_id == owner_id))
    row = SummaryRequestOutbox(
        event_id=event_id, meeting_id=meeting_id, transcript_id=transcript.id,
        template_id=template.id if template else None,
        template_version=template.version if template else None,
        instructions_snapshot=template.instructions if template else None,
        generation=await repository.next_generation(session, transcript.id), status="failed",
        failure_cause="request_failed" if template else "no_default_template", delivered_at=None,
        requested_at=now, finished_at=now,
    )
    session.add(row)
    await session.flush()
    return row
