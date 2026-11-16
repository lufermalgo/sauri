"""Authenticated, owner-scoped summary-template API."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.http_errors import NOT_FOUND, SafeErrorRoute, api_error, set_page_headers
from app.meetings.schemas import ResourceId
from app.templates import repository, service
from app.templates.schemas import (
    CategoryCreate,
    CategoryOut,
    DefaultTemplateSelection,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"], route_class=SafeErrorRoute)

# Same paging contract as the meeting list: a bare list, X-Total-Count and Link headers.
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
MAX_LIST_OFFSET = 1_000_000
Limit = Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)]
Offset = Annotated[int, Query(ge=0, le=MAX_LIST_OFFSET)]


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()


Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(data: TemplateCreate, session: Session, user: AuthorizedUser) -> TemplateOut:
    async with session.begin():
        row = await service.create_template(session, user.id, data)
    await session.refresh(row)
    return service.template_out(row, await repository.get_default_id(session, user.id))


@router.get("")
async def list_templates(
    request: Request, response: Response, session: Session, user: AuthorizedUser,
    limit: Limit = DEFAULT_LIST_LIMIT, offset: Offset = 0,
) -> list[TemplateOut]:
    rows = await repository.list_templates(session, user.id, limit, offset)
    set_page_headers(
        response, request, await repository.count_templates(session, user.id), limit, offset, len(rows),
    )
    default_id = await repository.get_default_id(session, user.id)
    return [service.template_out(row, default_id) for row in rows]


# Literal /categories must precede /{template_id} for GET route matching.
@router.get("/categories")
async def list_categories(
    request: Request, response: Response, session: Session, user: AuthorizedUser,
    limit: Limit = DEFAULT_LIST_LIMIT, offset: Offset = 0,
) -> list[CategoryOut]:
    rows = await repository.list_categories(session, user.id, limit, offset)
    set_page_headers(
        response, request, await repository.count_categories(session, user.id), limit, offset, len(rows),
    )
    return [service.category_out(row) for row in rows]


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(data: CategoryCreate, session: Session, user: AuthorizedUser) -> CategoryOut:
    async with session.begin():
        row = await service.create_category(session, user.id, data)
    await session.refresh(row)
    return service.category_out(row)


@router.put("/default", status_code=status.HTTP_204_NO_CONTENT)
async def set_default_template(data: DefaultTemplateSelection, session: Session, user: AuthorizedUser) -> None:
    async with session.begin():
        await service.set_default_template(session, user.id, data.template_id)


@router.get("/{template_id}")
async def get_template(template_id: ResourceId, session: Session, user: AuthorizedUser) -> TemplateOut:
    row = await repository.get_template(session, user.id, template_id)
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return service.template_out(row, await repository.get_default_id(session, user.id))


@router.patch("/{template_id}")
async def update_template(
    template_id: ResourceId, data: TemplateUpdate, session: Session, user: AuthorizedUser,
) -> TemplateOut:
    async with session.begin():
        row = await service.update_template(session, user.id, template_id, data)
    await session.refresh(row)
    return service.template_out(row, await repository.get_default_id(session, user.id))
