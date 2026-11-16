"""Personal template/category operations and ownership validation (R3/R4)."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.copy.templates_es import (
    DEFAULT_INSTRUCTIONS_V2,
    DEFAULT_NAME,
    DEFAULT_PROVENANCE,
    DEFAULT_PROVENANCE_V2,
)
from app.infra.http_errors import INVALID_REQUEST, NOT_FOUND, api_error
from app.infra.models import SummaryTemplate, TemplateCategory
from app.templates import repository
from app.templates.schemas import CategoryCreate, CategoryOut, TemplateCreate, TemplateOut, TemplateUpdate
from app.templates.seed import seed_id


def _provenance(row: SummaryTemplate, default_id: str | None) -> str | None:
    """Owner-proposal note, shown only while the starter template is unchanged."""
    if row.id != seed_id(row.owner_user_id, "template"):
        # Migration 021 moves a legacy-id default (created by an earlier mechanism) to the v2
        # text; its category is unknown, so the unedited check is the text and the starter name.
        if row.id == default_id and row.instructions == DEFAULT_INSTRUCTIONS_V2 and row.name == DEFAULT_NAME:
            return DEFAULT_PROVENANCE_V2
        return None
    if row.version == 1 and row.updated_at == row.created_at and row.instructions != DEFAULT_INSTRUCTIONS_V2:
        return DEFAULT_PROVENANCE
    # Version 2 text also reaches owners through migration 020, which bumps version and updated_at,
    # so unedited means: same text, name and category as the seed.
    if (
        row.instructions == DEFAULT_INSTRUCTIONS_V2 and row.name == DEFAULT_NAME
        and row.category_id == seed_id(row.owner_user_id, "category")
    ):
        return DEFAULT_PROVENANCE_V2
    return None


def template_out(row: SummaryTemplate, default_id: str | None) -> TemplateOut:
    return TemplateOut(
        id=row.id, name=row.name, instructions=row.instructions,
        owner_user_id=row.owner_user_id, category_id=row.category_id,
        version=row.version, is_default=row.id == default_id,
        provenance=_provenance(row, default_id),
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
        raise api_error(422, INVALID_REQUEST)


async def set_default_template(session: AsyncSession, owner_id: str, template_id: str) -> None:
    if await repository.get_template(session, owner_id, template_id) is None:
        # The same response for foreign and missing IDs avoids disclosing ownership.
        raise api_error(422, INVALID_REQUEST)
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
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    supplied = data.model_fields_set
    if ("name" in supplied and data.name is None) or ("instructions" in supplied and data.instructions is None):
        raise api_error(422, INVALID_REQUEST)
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
