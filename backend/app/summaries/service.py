"""Atomic, owner-scoped acceptance of an immutable summary request."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SummaryRequestOutbox
from app.summaries import repository


async def accept_request(
    session: AsyncSession, meeting_id: str, owner_id: str, template_id: str | None,
) -> SummaryRequestOutbox:
    meeting = await repository.owned_meeting_locked(session, meeting_id, owner_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    transcript = await repository.transcript_for_meeting(session, meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    template = await repository.selected_template(session, owner_id, template_id)
    if template is None:
        if template_id is None:
            raise HTTPException(status_code=503, detail="Default summary template unavailable")
        raise HTTPException(status_code=422, detail="Invalid template_id")
    row = SummaryRequestOutbox(
        event_id=str(uuid4()), meeting_id=meeting_id, transcript_id=transcript.id,
        template_id=template.id, template_version=template.version,
        instructions_snapshot=template.instructions,
        generation=await repository.next_generation(session, transcript.id), status="pending",
        delivered_at=None,
    )
    session.add(row)
    await session.flush()
    return row
