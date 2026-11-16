"""GET /api/v1/meetings: recording date fields, server-side date sort and stable pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting

OWNER = "recorded-at-owner"
BASE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _headers(user_id: str = OWNER) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Recorded At Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _seed(api_db_url: str, rows: list[tuple[str, int, int | None, str | None]]) -> None:
    """Rows are (id, received day offset, recorded day offset or None, source)."""
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        for meeting_id, received, recorded, source in rows:
            session.add(Meeting(
                id=meeting_id, meet_link=None, origin="manual", process_state="completed",
                created_by=OWNER, created_at=BASE + timedelta(days=received), title=meeting_id,
                recorded_at=None if recorded is None else BASE + timedelta(days=recorded),
                recorded_at_source=source,
            ))
    await engine.dispose()


# "old" was uploaded last but recorded first; "legacy" has no recording date at all.
ROWS = [
    ("old", 10, -200, "file_metadata"),
    ("mid", 5, 4, "file_modified"),
    ("new", 1, 1, "capture"),
    ("legacy", 3, None, None),
]


async def _ids(client: AsyncClient, query: str = "") -> list[str]:
    response = await client.get(f"/api/v1/meetings/{query}", headers=_headers())
    assert response.status_code == 200
    return [item["meeting_id"] for item in response.json()]


@pytest.mark.asyncio
async def test_list_exposes_the_recording_date_and_its_source(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, ROWS)
    response = await api_client.get("/api/v1/meetings/", headers=_headers())
    items = {item["meeting_id"]: item for item in response.json()}

    assert items["old"]["recorded_at_source"] == "file_metadata"
    assert items["old"]["recorded_at"].startswith((BASE + timedelta(days=-200)).strftime("%Y-%m-%d"))
    assert items["old"]["created_at"].startswith((BASE + timedelta(days=10)).strftime("%Y-%m-%d"))
    # A row older than the column reports the receipt date as its recording date.
    assert items["legacy"]["recorded_at"] == items["legacy"]["created_at"]
    assert items["legacy"]["recorded_at_source"] == "received"


@pytest.mark.asyncio
async def test_default_order_is_most_recently_recorded_first(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, ROWS)
    # recorded: mid (+4), legacy (received +3), new (+1), old (-200)
    assert await _ids(api_client) == ["mid", "legacy", "new", "old"]
    assert await _ids(api_client, "?sort=recorded_desc") == ["mid", "legacy", "new", "old"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sort", "expected"), [
    ("recorded_asc", ["old", "new", "legacy", "mid"]),
    ("processed_desc", ["old", "mid", "legacy", "new"]),
    ("processed_asc", ["new", "legacy", "mid", "old"]),
])
async def test_each_date_sort_orders_by_its_own_field(
    api_client: AsyncClient, api_db_url: str, sort: str, expected: list[str]
) -> None:
    await _seed(api_db_url, ROWS)
    assert await _ids(api_client, f"?sort={sort}") == expected


@pytest.mark.asyncio
async def test_unknown_sort_is_rejected(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, ROWS)
    response = await api_client.get("/api/v1/meetings/?sort=title", headers=_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["recorded_desc", "recorded_asc", "processed_desc", "processed_asc"])
async def test_pages_follow_the_sort_without_repeating_or_skipping(
    api_client: AsyncClient, api_db_url: str, sort: str
) -> None:
    # Equal dates: only the id tie-breaker keeps pages from overlapping.
    await _seed(api_db_url, [(f"m{i}", 0, 0, "received") for i in range(5)] + ROWS)
    everything = await _ids(api_client, f"?sort={sort}")
    paged: list[str] = []
    for offset in range(0, len(everything), 3):
        paged += await _ids(api_client, f"?sort={sort}&limit=3&offset={offset}")
    assert paged == everything
    assert len(set(everything)) == len(everything) == 9


@pytest.mark.asyncio
async def test_next_link_keeps_the_chosen_sort(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, ROWS)
    response = await api_client.get("/api/v1/meetings/?sort=processed_asc&limit=2", headers=_headers())
    assert "sort=processed_asc" in response.headers["Link"]


@pytest.mark.asyncio
async def test_detail_reports_the_recording_date(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, ROWS)
    body = (await api_client.get("/api/v1/meetings/old", headers=_headers())).json()
    assert body["recorded_at_source"] == "file_metadata"
    assert body["recorded_at"].startswith((BASE + timedelta(days=-200)).strftime("%Y-%m-%d"))
