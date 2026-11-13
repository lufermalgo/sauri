"""RED HTTP contracts for personal summary templates and categories (T5 #273).

Spec: meeting-summaries-templates R3/R4, design template API and route-order guard.
Uses the actual FastAPI app, JWT authentication, and isolated synthetic persistence;
no template router or repository is replaced by a test double.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import SummaryTemplate, TemplateCategory, User
from app.main import app

OWNER = str(uuid4())
OTHER = str(uuid4())
BASE = "/api/v1/templates"


def _headers(user_id: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id, f'{user_id}@sauri.local', 'Test', True)}"}


@pytest.fixture
async def template_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """A fresh DB shared across real HTTP requests, including ORM ownership checks."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'templates.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        for user_id in (OWNER, OTHER):
            session.add(User(
                id=user_id, email=f"{user_id}@sauri.local", name="Synthetic user",
                password_hash="not-used-by-jwt", is_sales=True, created_at=datetime.now(UTC),
            ))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory
    await engine.dispose()


async def _seed_category(
    factory: async_sessionmaker[AsyncSession], owner: str, name: str,
) -> str:
    category_id = str(uuid4())
    async with factory() as session, session.begin():
        session.add(TemplateCategory(
            id=category_id, owner_user_id=owner, name=name, created_at=datetime.now(UTC),
        ))
    return category_id


async def _seed_template(
    factory: async_sessionmaker[AsyncSession], owner: str, category_id: str | None = None,
    instructions: str = "Private instructions",
) -> str:
    template_id = str(uuid4())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(SummaryTemplate(
            id=template_id, owner_user_id=owner, name="Private template",
            instructions=instructions, category_id=category_id,
            version=1, created_at=now, updated_at=now,
        ))
    return template_id


@pytest.mark.asyncio
async def test_create_list_read_edit_multiple_personal_templates(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = template_api
    first = {"name": "Arguments", "instructions": "Keep the exact wording; do not paraphrase."}
    second = {"name": "Decisions", "instructions": "List decisions."}
    created = []
    for payload in (first, second):
        response = await client.post(BASE, json=payload, headers=_headers())
        assert response.status_code == 201, response.text
        item = response.json()
        assert item["name"] == payload["name"]
        assert item["instructions"] == payload["instructions"]
        assert item["owner_user_id"] == OWNER
        assert item["category_id"] is None
        assert item["version"] == 1
        assert item["is_default"] is False
        created.append(item)

    listing = await client.get(BASE, headers=_headers())
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()} == {item["id"] for item in created}
    for item in created:
        fetched = await client.get(f"{BASE}/{item['id']}", headers=_headers())
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == item

    edited = await client.patch(
        f"{BASE}/{created[0]['id']}",
        json={"name": "Arguments v2", "instructions": "  Preserve punctuation.\n"},
        headers=_headers(),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["instructions"] == "  Preserve punctuation.\n"
    assert edited.json()["name"] == "Arguments v2"
    assert edited.json()["version"] == 2
    unchanged = await client.get(f"{BASE}/{created[1]['id']}", headers=_headers())
    assert unchanged.json() == created[1]


@pytest.mark.asyncio
async def test_categories_static_route_lists_only_owned_and_creates_owned(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    own_id = await _seed_category(factory, OWNER, "Owned category")
    foreign_id = await _seed_category(factory, OTHER, "Foreign category secret")
    # This literal path must match /categories ahead of /{template_id}.
    listing = await client.get("/api/v1/templates/categories", headers=_headers())
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()} == {own_id}
    assert foreign_id not in listing.text
    assert "Foreign category secret" not in listing.text
    created = await client.post(
        "/api/v1/templates/categories", json={"name": "Second category"}, headers=_headers(),
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Second category"
    assert created.json()["owner_user_id"] == OWNER
    listing = await client.get("/api/v1/templates/categories", headers=_headers())
    assert {item["id"] for item in listing.json()} == {own_id, created.json()["id"]}
    assert foreign_id not in listing.text
    async with factory() as session:
        saved = await session.get(TemplateCategory, created.json()["id"])
        assert saved is not None and saved.owner_user_id == OWNER


@pytest.mark.asyncio
async def test_optional_category_accepts_multiple_templates_in_one_owned_category(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    category_id = await _seed_category(factory, OWNER, "Shared grouping")
    ids = set()
    for name in ("First", "Second"):
        response = await client.post(
            BASE, json={"name": name, "instructions": name, "category_id": category_id},
            headers=_headers(),
        )
        assert response.status_code == 201, response.text
        assert response.json()["category_id"] == category_id
        ids.add(response.json()["id"])
    assert len(ids) == 2
    listing = await client.get(BASE, headers=_headers())
    assert {item["id"] for item in listing.json()} == ids
    async with factory() as session:
        rows = (await session.scalars(select(SummaryTemplate).where(
            SummaryTemplate.category_id == category_id,
        ))).all()
        assert {row.id for row in rows} == ids


@pytest.mark.asyncio
async def test_foreign_category_rejected_for_create_and_edit_without_mutation_or_disclosure(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    foreign_id = await _seed_category(factory, OTHER, "Secret category")
    own_id = await _seed_template(factory, OWNER)
    for payload, method, path in (
        ({"name": "Rejected", "instructions": "Keep private", "category_id": foreign_id}, "post", BASE),
        ({"category_id": foreign_id, "instructions": "Changed"}, "patch", f"{BASE}/{own_id}"),
    ):
        denied = await getattr(client, method)(path, json=payload, headers=_headers())
        assert denied.status_code == 422, denied.text
        assert "Secret category" not in denied.text
    async with factory() as session:
        owned = (await session.scalars(select(SummaryTemplate).where(
            SummaryTemplate.owner_user_id == OWNER,
        ))).all()
        assert len(owned) == 1
        assert owned[0].id == own_id
        assert owned[0].category_id is None
        assert owned[0].instructions == "Private instructions"


@pytest.mark.asyncio
async def test_foreign_template_read_edit_and_list_are_isolated_like_missing(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    foreign_category = await _seed_category(factory, OTHER, "Secret grouping")
    foreign_id = await _seed_template(factory, OTHER, foreign_category, "Secret foreign instructions")
    own_id = await _seed_template(factory, OWNER)
    listing = await client.get(BASE, headers=_headers())
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()} == {own_id}
    for secret in (foreign_id, foreign_category, "Secret foreign instructions", "Secret grouping"):
        assert secret not in listing.text
    for payload in (None, {"instructions": "Overwrite"}):
        path = f"{BASE}/{foreign_id}"
        missing_path = f"{BASE}/{uuid4()}"
        if payload is None:
            denied = await client.get(path, headers=_headers())
            missing = await client.get(missing_path, headers=_headers())
        else:
            denied = await client.patch(path, json=payload, headers=_headers())
            missing = await client.patch(missing_path, json=payload, headers=_headers())
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json()
        assert foreign_id not in denied.text
        assert foreign_category not in denied.text
    async with factory() as session:
        saved = await session.get(SummaryTemplate, foreign_id)
        assert saved is not None and saved.instructions == "Secret foreign instructions"
        assert saved.category_id == foreign_category


@pytest.mark.asyncio
async def test_setting_default_identifies_exactly_one_personal_template_across_categories(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """T7 #275 RED: R5.1/R5.3, category-blind personal default (P3/P7)."""
    client, factory = template_api
    first_category = await _seed_category(factory, OWNER, "First grouping")
    second_category = await _seed_category(factory, OWNER, "Second grouping")
    ids = [
        await _seed_template(factory, OWNER, first_category, "First"),
        await _seed_template(factory, OWNER, first_category, "Another in first"),
        await _seed_template(factory, OWNER, second_category, "Second"),
        await _seed_template(factory, OWNER, None, "Ungrouped"),
    ]
    for chosen in (ids[0], ids[2], ids[3]):
        selected = await client.put(f"{BASE}/default", json={"template_id": chosen}, headers=_headers())
        assert selected.status_code == 204, selected.text
        assert not selected.content
        listing = await client.get(BASE, headers=_headers())
        assert listing.status_code == 200, listing.text
        assert {item["id"] for item in listing.json()} == set(ids)
        assert {item["id"] for item in listing.json() if item["is_default"]} == {chosen}
        assert {item["id"]: item["category_id"] for item in listing.json()} == {
            ids[0]: first_category, ids[1]: first_category,
            ids[2]: second_category, ids[3]: None,
        }
        other_listing = await client.get(BASE, headers=_headers(OTHER))
        assert other_listing.status_code == 200 and other_listing.json() == []
        async with factory() as session:
            owner = await session.get(User, OWNER)
            other = await session.get(User, OTHER)
            assert owner is not None and owner.default_summary_template_id == chosen
            assert other is not None and other.default_summary_template_id is None


@pytest.mark.asyncio
async def test_foreign_default_selection_matches_missing_and_preserves_existing_defaults(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """T7 #275 RED: R5.2, no existence leak and no mutation on rejection."""
    client, factory = template_api
    own_id = await _seed_template(factory, OWNER)
    foreign_category = await _seed_category(factory, OTHER, "Secret grouping")
    foreign_id = await _seed_template(factory, OTHER, foreign_category, "Secret instructions")
    async with factory() as session, session.begin():
        owner = await session.get(User, OWNER)
        other = await session.get(User, OTHER)
        assert owner is not None and other is not None
        owner.default_summary_template_id = own_id
        other.default_summary_template_id = foreign_id
    denied = await client.put(f"{BASE}/default", json={"template_id": foreign_id}, headers=_headers())
    missing = await client.put(f"{BASE}/default", json={"template_id": str(uuid4())}, headers=_headers())
    assert denied.status_code == missing.status_code == 422
    assert denied.json() == missing.json()
    for secret in (foreign_id, foreign_category, "Secret grouping", "Secret instructions"):
        assert secret not in denied.text
    listing = await client.get(BASE, headers=_headers())
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json() if item["is_default"]} == {own_id}
    assert foreign_id not in listing.text
    async with factory() as session:
        owner = await session.get(User, OWNER)
        other = await session.get(User, OTHER)
        assert owner is not None and owner.default_summary_template_id == own_id
        assert other is not None and other.default_summary_template_id == foreign_id
