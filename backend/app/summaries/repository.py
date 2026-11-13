"""Request persistence; the caller owns the transaction."""

from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting, SummaryRequestOutbox, SummaryTemplate, Transcript, User


async def owned_meeting_locked(session: AsyncSession, meeting_id: str, owner_id: str) -> Meeting | None:
    # Serializes generation allocation on PostgreSQL, including the first request.
    return cast(Meeting | None, await session.scalar(select(Meeting).where(
        Meeting.id == meeting_id, Meeting.created_by == owner_id,
    ).with_for_update()))


async def transcript_for_meeting(session: AsyncSession, meeting_id: str) -> Transcript | None:
    return cast(Transcript | None, await session.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting_id)
    ))


async def selected_template(
    session: AsyncSession, owner_id: str, explicit_id: str | None,
) -> SummaryTemplate | None:
    template_id = explicit_id
    if template_id is None:
        template_id = await session.scalar(select(User.default_summary_template_id).where(User.id == owner_id))
    if template_id is None:
        return None
    return cast(SummaryTemplate | None, await session.scalar(select(SummaryTemplate).where(
        SummaryTemplate.id == template_id, SummaryTemplate.owner_user_id == owner_id,
    )))


async def next_generation(session: AsyncSession, transcript_id: str) -> int:
    latest = await session.scalar(select(func.max(SummaryRequestOutbox.generation)).where(
        SummaryRequestOutbox.transcript_id == transcript_id,
    ))
    return (latest or 0) + 1


async def request_for_owner(
    session: AsyncSession, meeting_id: str, owner_id: str, event_id: str | None = None,
) -> SummaryRequestOutbox | None:
    query = (select(SummaryRequestOutbox).join(Meeting, SummaryRequestOutbox.meeting_id == Meeting.id)
             .where(Meeting.id == meeting_id, Meeting.created_by == owner_id))
    if event_id is not None:
        query = query.where(SummaryRequestOutbox.event_id == event_id)
    else:
        query = query.order_by(SummaryRequestOutbox.generation.desc()).limit(1)
    return cast(SummaryRequestOutbox | None, await session.scalar(query))
