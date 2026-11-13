"""T6 #274: JWT/sales gate, PATCH omission/null and persisted version/category behavior.

The original T5 RED commit and its five assertions are unchanged.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.token import create_token
from app.infra.models import AccessLog, SummaryTemplate
from tests.templates.test_templates_api import BASE, OTHER, OWNER, _headers, _seed_category

pytest_plugins = ["tests.templates.test_templates_api"]


@pytest.mark.asyncio
async def test_patch_omission_null_and_category_removal_persist(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    category = await _seed_category(factory, OWNER, "Private grouping")
    created = await client.post(
        BASE, json={"name": "Original", "instructions": "Opaque instructions\n", "category_id": category},
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    renamed = await client.patch(f"{BASE}/{template_id}", json={"name": "Renamed"}, headers=_headers())
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["instructions"] == "Opaque instructions\n"
    assert renamed.json()["version"] == 1
    assert renamed.json()["category_id"] == category
    cleared = await client.patch(f"{BASE}/{template_id}", json={"category_id": None}, headers=_headers())
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["category_id"] is None
    for payload in ({"instructions": None}, {"name": None}, {"name": ""}):
        denied = await client.patch(f"{BASE}/{template_id}", json=payload, headers=_headers())
        assert denied.status_code == 422, denied.text
    replaced = await client.patch(
        f"{BASE}/{template_id}", json={"instructions": "  exact replacement\n"}, headers=_headers(),
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["instructions"] == "  exact replacement\n"
    assert replaced.json()["version"] == 2
    async with factory() as session:
        saved = await session.get(SummaryTemplate, template_id)
        assert saved is not None
        assert (saved.name, saved.instructions, saved.category_id, saved.version) == (
            "Renamed", "  exact replacement\n", None, 2,
        )


@pytest.mark.asyncio
async def test_authentication_and_sales_gate_apply_to_all_template_routes(
    template_api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = template_api
    no_sales = {"Authorization": "Bearer " + create_token(
        OTHER, f"{OTHER}@sauri.local", "Other user", False,
    )}
    endpoints = (
        ("get", BASE, None),
        ("post", BASE, {"name": "Not saved", "instructions": "Nope"}),
        ("get", f"{BASE}/{uuid4()}", None),
        ("patch", f"{BASE}/{uuid4()}", {"instructions": "Nope"}),
        ("get", f"{BASE}/categories", None),
        ("post", f"{BASE}/categories", {"name": "Not saved"}),
        ("put", f"{BASE}/default", {"template_id": str(uuid4())}),
    )
    for method, path, payload in endpoints:
        unauthenticated = await client.request(method.upper(), path, json=payload)
        assert unauthenticated.status_code == 401, unauthenticated.text
        forbidden = await client.request(method.upper(), path, json=payload, headers=no_sales)
        assert forbidden.status_code == 403, forbidden.text
    async with factory() as session:
        logs = (await session.scalars(select(AccessLog).where(AccessLog.user_id == OTHER))).all()
        assert len(logs) == len(endpoints)
        assert all(log.result == "denied" for log in logs)
        assert (await session.scalars(select(SummaryTemplate))).all() == []
    allowed = await client.get(BASE, headers=_headers())
    assert allowed.status_code == 200 and allowed.json() == []
