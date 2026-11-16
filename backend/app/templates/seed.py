"""Editable, owner-isolated copies of the system's starter template."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.copy.templates_es import DEFAULT_CATEGORY, DEFAULT_INSTRUCTIONS_V2, DEFAULT_NAME
from app.infra.models import SummaryTemplate, TemplateCategory, User


def seed_id(owner_id: str, kind: str) -> str:
    # The identity stays version-independent: migration 020 upgrades unedited v1 templates in
    # place, so migrated owners and new owners share one seeded id scheme.
    return str(uuid5(NAMESPACE_URL, f"sauri:summary-default:2026-11-14:{kind}:{owner_id}"))


async def ensure_default(session: AsyncSession, owner_id: str) -> str | None:
    # Lock the owner, not only one meeting: simultaneous requests for different meetings
    # must not create competing defaults. Existing personal preferences always win.
    user = await session.scalar(select(User).where(User.id == owner_id).with_for_update())
    if user is None:
        return None
    if user.default_summary_template_id is not None:
        return user.default_summary_template_id
    now = datetime.now(UTC)
    category_id, template_id = seed_id(owner_id, "category"), seed_id(owner_id, "template")
    if await session.get(TemplateCategory, category_id) is None:
        session.add(TemplateCategory(id=category_id, owner_user_id=owner_id, name=DEFAULT_CATEGORY, created_at=now))
        await session.flush()
    if await session.get(SummaryTemplate, template_id) is None:
        session.add(SummaryTemplate(
            id=template_id, owner_user_id=owner_id, category_id=category_id,
            name=DEFAULT_NAME, instructions=DEFAULT_INSTRUCTIONS_V2, version=1, created_at=now, updated_at=now,
        ))
        await session.flush()
    user.default_summary_template_id = template_id
    await session.flush()
    return template_id
