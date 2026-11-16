"""Owner-scoped persistence for personal templates; caller owns transactions."""

from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SummaryTemplate, TemplateCategory, User


async def list_templates(
    session: AsyncSession, owner_id: str, limit: int, offset: int = 0,
) -> list[SummaryTemplate]:
    rows = await session.scalars(
        select(SummaryTemplate).where(SummaryTemplate.owner_user_id == owner_id)
        .order_by(SummaryTemplate.created_at, SummaryTemplate.id).limit(limit).offset(offset)
    )
    return list(rows.all())


async def count_templates(session: AsyncSession, owner_id: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(SummaryTemplate).where(SummaryTemplate.owner_user_id == owner_id)
    ) or 0)


async def get_template(session: AsyncSession, owner_id: str, template_id: str) -> SummaryTemplate | None:
    return cast(SummaryTemplate | None, await session.scalar(
        select(SummaryTemplate).where(SummaryTemplate.owner_user_id == owner_id, SummaryTemplate.id == template_id)
    ))


async def list_categories(
    session: AsyncSession, owner_id: str, limit: int, offset: int = 0,
) -> list[TemplateCategory]:
    rows = await session.scalars(
        select(TemplateCategory).where(TemplateCategory.owner_user_id == owner_id)
        .order_by(TemplateCategory.created_at, TemplateCategory.id).limit(limit).offset(offset)
    )
    return list(rows.all())


async def count_categories(session: AsyncSession, owner_id: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(TemplateCategory).where(TemplateCategory.owner_user_id == owner_id)
    ) or 0)


async def get_category(session: AsyncSession, owner_id: str, category_id: str) -> TemplateCategory | None:
    return cast(TemplateCategory | None, await session.scalar(
        select(TemplateCategory).where(TemplateCategory.owner_user_id == owner_id, TemplateCategory.id == category_id)
    ))


async def get_default_id(session: AsyncSession, owner_id: str) -> str | None:
    return await session.scalar(select(User.default_summary_template_id).where(User.id == owner_id))


async def set_default_id(session: AsyncSession, owner_id: str, template_id: str) -> None:
    await session.execute(
        update(User).where(User.id == owner_id).values(default_summary_template_id=template_id)
    )
