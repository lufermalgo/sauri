"""Authenticated owner-scoped summary artifacts and request status API."""

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.summaries import repository, service
from app.summaries.passages import KeyPoint
from app.templates.router import get_session

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}", tags=["summaries"])
Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]


class SummaryRequestInput(BaseModel):
    template_id: str | None = None


class SummaryRequestStatus(BaseModel):
    event_id: str
    generation: int
    status: str
    failure_cause: str | None = None


class SummaryResponse(BaseModel):
    summary_id: str
    meeting_id: str
    template_id: str
    template_name: str
    template_version: int
    topic: str
    key_points: list[KeyPoint | str]  # Legacy artifacts remain readable, without invented citations.
    review_state: Literal["draft"] = "draft"
    generation: int
    created_at: datetime
    updated_at: datetime


@router.get("/summary")
async def current_summary(meeting_id: str, session: Session, user: AuthorizedUser) -> SummaryResponse:
    result = await repository.current_summary_for_owner(session, meeting_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Summary not available")
    summary, template_name = result
    return SummaryResponse(
        summary_id=summary.id,
        meeting_id=summary.meeting_id,
        template_id=summary.template_id,
        template_name=template_name,
        template_version=summary.template_version,
        topic=summary.topic,
        key_points=json.loads(summary.key_points_json),
        generation=summary.generation,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


@router.post("/summary-requests", status_code=202, response_model_exclude_none=True)
async def request_summary(
    meeting_id: str,
    data: SummaryRequestInput,
    session: Session,
    user: AuthorizedUser,
) -> SummaryRequestStatus:
    async with session.begin():
        row = await service.accept_request(session, meeting_id, user.id, data.template_id)
    return SummaryRequestStatus(
        event_id=row.event_id, generation=row.generation, status=row.status, failure_cause=row.failure_cause,
    )


@router.get("/summary-requests/latest", response_model_exclude_none=True)
async def latest_request(meeting_id: str, session: Session, user: AuthorizedUser) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary request not found")
    return SummaryRequestStatus(
        event_id=row.event_id, generation=row.generation, status=row.status, failure_cause=row.failure_cause,
    )


@router.get("/summary-requests/{event_id}", response_model_exclude_none=True)
async def request_status(
    meeting_id: str,
    event_id: str,
    session: Session,
    user: AuthorizedUser,
) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary request not found")
    return SummaryRequestStatus(
        event_id=row.event_id, generation=row.generation, status=row.status, failure_cause=row.failure_cause,
    )
