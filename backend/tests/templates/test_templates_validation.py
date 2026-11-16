"""Bounded template, category and summary-request models; paging of the template lists."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import SummaryTemplate, TemplateCategory, User
from app.main import app
from app.summaries.router import SummaryRequestInput
from app.templates.schemas import (
    MAX_INSTRUCTIONS_CHARS,
    CategoryCreate,
    DefaultTemplateSelection,
    TemplateCreate,
    TemplateUpdate,
)

OWNER = str(uuid4())
OTHER = str(uuid4())
BASE = "/api/v1/templates"


def _headers(user_id: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id, f'{user_id}@sauri.local', 'Test', True)}"}


@pytest.fixture
async def api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'validation.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        for user_id in (OWNER, OTHER):
            session.add(User(
                id=user_id, email=f"{user_id}@sauri.local", name="Synthetic",
                password_hash="unused", is_sales=True, created_at=datetime.now(UTC),
            ))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory
    await engine.dispose()


async def _seed(factory: async_sessionmaker[AsyncSession], count: int, owner: str = OWNER) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    async with factory() as session, session.begin():
        for index in range(count):
            created = start + timedelta(minutes=index)
            session.add(TemplateCategory(
                id=str(uuid4()), owner_user_id=owner, name=f"Category {index}", created_at=created,
            ))
            session.add(SummaryTemplate(
                id=str(uuid4()), owner_user_id=owner, name=f"Template {index}", instructions="i",
                version=1, created_at=created, updated_at=created,
            ))


# --- models ---------------------------------------------------------------------------------------------


def test_instruction_limit_is_twenty_thousand_characters() -> None:
    assert MAX_INSTRUCTIONS_CHARS == 20_000
    assert TemplateCreate(name="n", instructions="i" * 20_000).instructions
    assert TemplateUpdate(instructions="i" * 20_000).instructions
    with pytest.raises(ValidationError):
        TemplateCreate(name="n", instructions="i" * 20_001)
    with pytest.raises(ValidationError):
        TemplateUpdate(instructions="i" * 20_001)


@pytest.mark.parametrize(
    "build",
    [
        lambda: TemplateCreate(name="n" * 129, instructions="i"),
        lambda: TemplateCreate(name="", instructions="i"),
        lambda: TemplateCreate(name="n", instructions=""),
        lambda: TemplateCreate(name="n", instructions="i", category_id="c" * 65),
        lambda: TemplateCreate(name="n", instructions="i", category_id="bad id"),
        lambda: TemplateCreate(name="n", instructions="i", owner_user_id="x"),
        lambda: TemplateUpdate(name="n" * 129),
        lambda: TemplateUpdate(version=9),
        lambda: CategoryCreate(name="c" * 129),
        lambda: CategoryCreate(name="c", owner_user_id="x"),
        lambda: DefaultTemplateSelection(template_id="t" * 65),
        lambda: DefaultTemplateSelection(template_id="t", other=1),
        lambda: SummaryRequestInput(template_id="t" * 65),
        lambda: SummaryRequestInput(model="gpt"),
    ],
)
def test_models_reject_out_of_bound_or_unknown_fields(build: Any) -> None:
    with pytest.raises(ValidationError):
        build()


def test_models_accept_the_bodies_the_portal_sends() -> None:
    assert SummaryRequestInput().template_id is None
    assert SummaryRequestInput(template_id=str(uuid4())).template_id
    assert TemplateCreate(name="n", instructions="i", category_id=None).category_id is None
    assert TemplateUpdate(category_id=None).model_fields_set == {"category_id"}
    assert CategoryCreate(name="c" * 128).name


# --- HTTP -----------------------------------------------------------------------------------------------


async def test_oversized_instructions_are_a_generic_422_that_does_not_echo_them(
    api: tuple[AsyncClient, Any],
) -> None:
    client, _ = api
    response = await client.post(
        BASE, json={"name": "n", "instructions": "SECRET" * 4000}, headers=_headers()
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"
    assert "SECRET" not in response.text
    ok = await client.post(
        BASE, json={"name": "n", "instructions": "i" * 20_000}, headers=_headers()
    )
    assert ok.status_code == 201


async def test_unknown_template_fields_are_rejected_on_every_write(api: tuple[AsyncClient, Any]) -> None:
    client, _ = api
    created = await client.post(BASE, json={"name": "n", "instructions": "i"}, headers=_headers())
    template_id = created.json()["id"]
    attempts = [
        client.post(BASE, json={"name": "n", "instructions": "i", "owner_user_id": OTHER}, headers=_headers()),
        client.patch(f"{BASE}/{template_id}", json={"owner_user_id": OTHER}, headers=_headers()),
        client.post(f"{BASE}/categories", json={"name": "c", "owner_user_id": OTHER}, headers=_headers()),
        client.put(f"{BASE}/default", json={"template_id": template_id, "x": 1}, headers=_headers()),
    ]
    for attempt in attempts:
        response = await attempt
        assert response.status_code == 422
        assert response.json()["detail"] == "invalid_request"
        assert OTHER not in response.text


async def test_foreign_and_missing_templates_stay_indistinguishable(api: tuple[AsyncClient, Any]) -> None:
    client, factory = api
    await _seed(factory, 1, owner=OTHER)
    async with factory() as session:
        foreign_id = (await session.execute(
            SummaryTemplate.__table__.select().where(SummaryTemplate.owner_user_id == OTHER)
        )).first().id  # type: ignore[union-attr]
    foreign = await client.get(f"{BASE}/{foreign_id}", headers=_headers())
    missing = await client.get(f"{BASE}/{uuid4()}", headers=_headers())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "not_found"}
    assert (await client.get(f"{BASE}/{'x' * 65}", headers=_headers())).status_code == 422
    default = await client.put(f"{BASE}/default", json={"template_id": foreign_id}, headers=_headers())
    assert default.status_code == 422
    assert default.json() == {"detail": "invalid_request"}


@pytest.mark.parametrize("path", ["", "/categories"])
async def test_template_lists_page_with_headers_and_keep_the_bare_list(
    api: tuple[AsyncClient, Any], path: str
) -> None:
    client, factory = api
    await _seed(factory, 5)
    await _seed(factory, 4, owner=OTHER)
    url = f"{BASE}{path}"

    everything = await client.get(url, headers=_headers())
    assert isinstance(everything.json(), list)
    assert everything.headers["X-Total-Count"] == "5"
    assert "Link" not in everything.headers

    first = await client.get(url, params={"limit": 2}, headers=_headers())
    second = await client.get(url, params={"limit": 2, "offset": 2}, headers=_headers())
    last = await client.get(url, params={"limit": 2, "offset": 4}, headers=_headers())
    names = [item["name"] for page in (first, second, last) for item in page.json()]
    assert len(names) == 5 and len(set(names)) == 5
    assert 'rel="next"' in first.headers["Link"] and "offset=2" in first.headers["Link"]
    assert "Link" not in last.headers
    past = await client.get(url, params={"offset": 50}, headers=_headers())
    assert past.json() == [] and past.headers["X-Total-Count"] == "5"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}, {"limit": "x"}])
@pytest.mark.parametrize("path", ["", "/categories"])
async def test_template_list_paging_bounds(
    api: tuple[AsyncClient, Any], path: str, params: dict[str, Any]
) -> None:
    client, _ = api
    response = await client.get(f"{BASE}{path}", params=params, headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"


async def test_summary_request_body_is_strict(api: tuple[AsyncClient, Any]) -> None:
    client, _ = api
    url = f"/api/v1/meetings/{uuid4()}/summary-requests"
    for body in ({"template_id": "t" * 65}, {"model": "x"}, {"template_id": "bad id"}):
        response = await client.post(url, json=body, headers=_headers())
        assert response.status_code == 422
        assert response.json()["detail"] == "invalid_request"
    # `{}` is what the portal sends; it passes validation and reaches the owner check.
    assert (await client.post(url, json={}, headers=_headers())).status_code == 404
