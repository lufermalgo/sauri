"""Owner-scoped persistence for personal templates; caller owns transactions."""

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SummaryTemplate, TemplateCategory, User


async def list_templates(session: AsyncSession, owner_id: str) -> list[SummaryTemplate]:
    rows = await session.scalars(
        select(SummaryTemplate).where(SummaryTemplate.owner_user_id == owner_id).order_by(SummaryTemplate.created_at)
    )
    return list(rows.all())


async def get_template(session: AsyncSession, owner_id: str, template_id: str) -> SummaryTemplate | None:
    return cast(SummaryTemplate | None, await session.scalar(
        select(SummaryTemplate).where(SummaryTemplate.owner_user_id == owner_id, SummaryTemplate.id == template_id)
    ))


async def list_categories(session: AsyncSession, owner_id: str) -> list[TemplateCategory]:
    rows = await session.scalars(
        select(TemplateCategory).where(TemplateCategory.owner_user_id == owner_id).order_by(TemplateCategory.created_at)
    )
    return list(rows.all())


async def get_category(session: AsyncSession, owner_id: str, category_id: str) -> TemplateCategory | None:
    return cast(TemplateCategory | None, await session.scalar(
        select(TemplateCategory).where(TemplateCategory.owner_user_id == owner_id, TemplateCategory.id == category_id)
    ))


async def get_default_id(session: AsyncSession, owner_id: str) -> str | None:
    return await session.scalar(select(User.default_summary_template_id).where(User.id == owner_id))
