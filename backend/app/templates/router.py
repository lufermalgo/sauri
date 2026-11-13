"""Authenticated, owner-scoped summary-template API."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.templates import repository, service
from app.templates.schemas import (
    CategoryCreate,
    CategoryOut,
    DefaultTemplateSelection,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


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
async def list_templates(session: Session, user: AuthorizedUser) -> list[TemplateOut]:
    rows = await repository.list_templates(session, user.id)
    default_id = await repository.get_default_id(session, user.id)
    return [service.template_out(row, default_id) for row in rows]


# Literal /categories must precede /{template_id} for GET route matching.
@router.get("/categories")
async def list_categories(session: Session, user: AuthorizedUser) -> list[CategoryOut]:
    return [service.category_out(row) for row in await repository.list_categories(session, user.id)]


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
async def get_template(template_id: str, session: Session, user: AuthorizedUser) -> TemplateOut:
    row = await repository.get_template(session, user.id, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return service.template_out(row, await repository.get_default_id(session, user.id))


@router.patch("/{template_id}")
async def update_template(
    template_id: str, data: TemplateUpdate, session: Session, user: AuthorizedUser,
) -> TemplateOut:
    async with session.begin():
        row = await service.update_template(session, user.id, template_id, data)
    await session.refresh(row)
    return service.template_out(row, await repository.get_default_id(session, user.id))
