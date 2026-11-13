"""Authenticated owner-scoped summary request API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.summaries import repository, service
from app.templates.router import get_session

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}/summary-requests", tags=["summaries"])
Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]


class SummaryRequestInput(BaseModel):
    template_id: str | None = None


class SummaryRequestStatus(BaseModel):
    event_id: str
    generation: int
    status: str


@router.post("", status_code=202)
async def request_summary(
    meeting_id: str, data: SummaryRequestInput, session: Session, user: AuthorizedUser,
) -> SummaryRequestStatus:
    async with session.begin():
        row = await service.accept_request(session, meeting_id, user.id, data.template_id)
    return SummaryRequestStatus(event_id=row.event_id, generation=row.generation, status=row.status)


@router.get("/latest")
async def latest_request(meeting_id: str, session: Session, user: AuthorizedUser) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary request not found")
    return SummaryRequestStatus(event_id=row.event_id, generation=row.generation, status=row.status)


@router.get("/{event_id}")
async def request_status(
    meeting_id: str, event_id: str, session: Session, user: AuthorizedUser,
) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary request not found")
    return SummaryRequestStatus(event_id=row.event_id, generation=row.generation, status=row.status)
