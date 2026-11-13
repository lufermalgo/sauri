"""Personal template/category operations and ownership validation (R3/R4)."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SummaryTemplate, TemplateCategory
from app.templates import repository
from app.templates.schemas import CategoryCreate, CategoryOut, TemplateCreate, TemplateOut, TemplateUpdate


def template_out(row: SummaryTemplate, default_id: str | None) -> TemplateOut:
    return TemplateOut(
        id=row.id, name=row.name, instructions=row.instructions,
        owner_user_id=row.owner_user_id, category_id=row.category_id,
        version=row.version, is_default=row.id == default_id,
        created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat(),
    )


def category_out(row: TemplateCategory) -> CategoryOut:
    return CategoryOut(
        id=row.id, name=row.name, owner_user_id=row.owner_user_id,
        created_at=row.created_at.isoformat(),
    )


async def validate_category(session: AsyncSession, owner_id: str, category_id: str | None) -> None:
    if category_id is not None and await repository.get_category(session, owner_id, category_id) is None:
        # Identical response for missing and foreign category; no existence leak.
        raise HTTPException(status_code=422, detail="Invalid category_id")


async def set_default_template(session: AsyncSession, owner_id: str, template_id: str) -> None:
    if await repository.get_template(session, owner_id, template_id) is None:
        # The same response for foreign and missing IDs avoids disclosing ownership.
        raise HTTPException(status_code=422, detail="Invalid template_id")
    await repository.set_default_id(session, owner_id, template_id)


async def create_template(session: AsyncSession, owner_id: str, data: TemplateCreate) -> SummaryTemplate:
    await validate_category(session, owner_id, data.category_id)
    now = datetime.now(UTC)
    row = SummaryTemplate(
        id=str(uuid4()), owner_user_id=owner_id, name=data.name,
        instructions=data.instructions, category_id=data.category_id,
        version=1, created_at=now, updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def update_template(
    session: AsyncSession, owner_id: str, template_id: str, data: TemplateUpdate,
) -> SummaryTemplate:
    row = await repository.get_template(session, owner_id, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    supplied = data.model_fields_set
    if ("name" in supplied and data.name is None) or ("instructions" in supplied and data.instructions is None):
        raise HTTPException(status_code=422, detail="name and instructions cannot be null")
    if "category_id" in supplied:
        await validate_category(session, owner_id, data.category_id)
        row.category_id = data.category_id
    if "name" in supplied and data.name is not None:
        row.name = data.name
    if "instructions" in supplied and data.instructions is not None:
        # Supplied instructions replace the opaque payload and advance its version,
        # even when the new string happens to be identical to the old one.
        row.instructions = data.instructions
        row.version += 1
    if supplied:
        row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def create_category(session: AsyncSession, owner_id: str, data: CategoryCreate) -> TemplateCategory:
    row = TemplateCategory(
        id=str(uuid4()), owner_user_id=owner_id, name=data.name, created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row
