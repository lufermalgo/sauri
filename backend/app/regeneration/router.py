"""Authenticated, owner-scoped API to explicitly regenerate one pipeline stage (#1053)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.infra.models import Meeting
from app.infra.object_store import ObjectStore, create_object_store
from app.infra.queue import JobQueue, create_job_queue
from app.regeneration import service
from app.templates.router import get_session

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}/regenerate", tags=["regeneration"])
logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]


def _get_queue() -> JobQueue:
    return create_job_queue()


def _get_object_store() -> ObjectStore:
    return create_object_store()


class RegenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["transcription", "speakers", "summary"]
    template_id: str | None = None
    # Also regenerate every later stage, one turn at a time. Off unless asked for.
    cascade: bool = False

    @model_validator(mode="after")
    def validate_combination(self) -> RegenerateInput:
        if self.cascade and self.stage == "summary":
            raise ValueError("cascade has no later stage after the summary")
        if self.template_id is not None and self.stage != "summary" and not self.cascade:
            raise ValueError("template_id only applies to a summary or a cascade that ends in one")
        return self


class RegenerationStatus(BaseModel):
    operation_id: str
    meeting_id: str
    stage: str
    status: str
    cascade: bool
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_cause: str | None = None
    # Stages this run computes again, and existing later outputs left stale (kept visible).
    replaces: list[str]
    stale: list[str]
    parent_operation_id: str | None = None
    next_operation_id: str | None = None
    summary_request_id: str | None = None
    details: dict[str, Any] | None = None


async def _status(session: AsyncSession, op: Any) -> RegenerationStatus:
    return RegenerationStatus(**await service.operation_view(session, op))


@router.post("", status_code=202, response_model_exclude_none=True)
async def regenerate(
    meeting_id: str,
    data: RegenerateInput,
    session: Session,
    user: AuthorizedUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=256)] = None,
) -> RegenerationStatus:
    async with session.begin():
        accepted = await service.request_regeneration(
            session, _get_object_store(), meeting_id=meeting_id, owner_id=user.id, stage=data.stage,
            template_id=data.template_id, cascade=data.cascade, idempotency_key=idempotency_key,
        )
    operation_id = accepted.operation.id
    if accepted.dispatch is not None:
        await _publish(session, operation_id, accepted.dispatch)
    async with session.begin():
        return await _status(session, accepted.operation)


async def _publish(session: AsyncSession, operation_id: str, dispatch: service.Dispatch) -> None:
    """Publish after commit; a lost message must not leave the meeting blocked."""
    queue = _get_queue()
    try:
        await queue.connect()
        try:
            await queue.publish(dispatch.topic, dispatch.message)
        finally:
            await queue.disconnect()
    except Exception as exc:
        logger.error("Regeneration publication failed for operation_id=%s", operation_id)
        async with session.begin():
            op = await service.locked_any_operation(session, operation_id)
            if op is not None:
                await service.fail_operation(session, op, service.QUEUE_CAUSE)
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable"}) from exc


async def _require_owned(session: AsyncSession, meeting_id: str, owner_id: str) -> None:
    owned = await session.scalar(
        select(Meeting.id).where(Meeting.id == meeting_id, Meeting.created_by == owner_id)
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Meeting not found")


@router.get("/latest", response_model_exclude_none=True)
async def latest_regeneration(meeting_id: str, session: Session, user: AuthorizedUser) -> RegenerationStatus:
    async with session.begin():
        await _require_owned(session, meeting_id, user.id)
        await service.settle_summary_operations(session)
        op = await service.latest_operation(session, meeting_id)
        if op is None:
            raise HTTPException(status_code=404, detail="Regeneration not found")
        return await _status(session, op)


@router.get("/{operation_id}", response_model_exclude_none=True)
async def regeneration_status(
    meeting_id: str, operation_id: str, session: Session, user: AuthorizedUser
) -> RegenerationStatus:
    async with session.begin():
        await _require_owned(session, meeting_id, user.id)
        await service.settle_summary_operations(session)
        op = await service.operation_for_meeting(session, meeting_id, operation_id)
        if op is None:
            raise HTTPException(status_code=404, detail="Regeneration not found")
        return await _status(session, op)
