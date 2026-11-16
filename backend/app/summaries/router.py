"""Authenticated owner-scoped summary artifacts and request status API."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.infra.http_errors import NOT_FOUND, SafeErrorRoute, api_error
from app.infra.models import SummaryRequestOutbox
from app.meetings.schemas import ResourceId
from app.summaries import repository, service
from app.summaries.passages import KeyPoint, KeyPointBlock, decode_key_points
from app.templates.router import get_session

router = APIRouter(
    prefix="/api/v1/meetings/{meeting_id}", tags=["summaries"], route_class=SafeErrorRoute
)
Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]


class SummaryRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: ResourceId | None = None


class SummaryRequestStatus(BaseModel):
    event_id: str
    generation: int
    status: str
    failure_cause: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _request_status(row: SummaryRequestOutbox) -> SummaryRequestStatus:
    return SummaryRequestStatus(
        event_id=row.event_id, generation=row.generation, status=row.status, failure_cause=row.failure_cause,
        requested_at=_utc(row.requested_at), started_at=_utc(row.started_at),
    )


class SummaryResponse(BaseModel):
    summary_id: str
    meeting_id: str
    template_id: str
    template_name: str
    template_version: int
    topic: str
    schema_version: int = 1
    key_points: list[KeyPointBlock | KeyPoint | str]  # Legacy artifacts remain readable, without invented citations.
    conclusion: str | None = None
    review_state: Literal["draft"] = "draft"
    generation: int
    created_at: datetime
    updated_at: datetime


@router.get("/summary")
async def current_summary(meeting_id: ResourceId, session: Session, user: AuthorizedUser) -> SummaryResponse:
    result = await repository.current_summary_for_owner(session, meeting_id, user.id)
    if result is None:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    summary, template_name = result
    content = decode_key_points(summary.key_points_json)
    return SummaryResponse(
        summary_id=summary.id,
        meeting_id=summary.meeting_id,
        template_id=summary.template_id,
        template_name=template_name,
        template_version=summary.template_version,
        topic=summary.topic,
        schema_version=content.schema_version,
        key_points=content.key_points,
        conclusion=content.conclusion,
        generation=summary.generation,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


@router.post("/summary-requests", status_code=202, response_model_exclude_none=True)
async def request_summary(
    meeting_id: ResourceId,
    data: SummaryRequestInput,
    session: Session,
    user: AuthorizedUser,
) -> SummaryRequestStatus:
    async with session.begin():
        row = await service.accept_request(session, meeting_id, user.id, data.template_id)
    return _request_status(row)


@router.get("/summary-requests/latest", response_model_exclude_none=True)
async def latest_request(meeting_id: ResourceId, session: Session, user: AuthorizedUser) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id)
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return _request_status(row)


@router.get("/summary-requests/{event_id}", response_model_exclude_none=True)
async def request_status(
    meeting_id: ResourceId,
    event_id: ResourceId,
    session: Session,
    user: AuthorizedUser,
) -> SummaryRequestStatus:
    row = await repository.request_for_owner(session, meeting_id, user.id, event_id)
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return _request_status(row)
