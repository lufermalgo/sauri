"""Typed, bounded request models, pagination and signed-link lifetime of the meeting API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting
from app.meetings.schemas import MAX_INT32, MeetingCreate
from app.meetings.signed_urls import (
    DEFAULT_PLAYBACK_URL_TTL_SECONDS,
    DEFAULT_SIGNED_URL_TTL_SECONDS,
    playback_url_ttl_seconds,
    signed_url_ttl_seconds,
)

OWNER = "validation-owner"
OTHER = "validation-other"
BASE = "/api/v1/meetings"
LINK = "https://meet.google.com/abc-defg-hij"


def _headers(user_id: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id, f'{user_id}@sauri.local', 'Synthetic', True)}"}


async def _seed(db_url: str, count: int, owner: str = OWNER) -> list[str]:
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ids = [str(uuid.uuid4()) for _ in range(count)]
    async with factory() as session, session.begin():
        for index, meeting_id in enumerate(ids):
            session.add(Meeting(
                id=meeting_id, meet_link=LINK, title=f"Note {index}", origin="link",
                process_state="queued", created_by=owner,
                created_at=start + timedelta(minutes=index),
            ))
    await engine.dispose()
    return ids


# --- MeetingCreate ------------------------------------------------------------------------------


def test_meeting_create_accepts_the_shapes_the_clients_send() -> None:
    assert MeetingCreate(meet_link=LINK).model_dump(exclude_none=True) == {"meet_link": LINK}
    assert MeetingCreate(meet_link=LINK, type="manual").type == "manual"
    when = datetime.now(UTC)
    assert MeetingCreate(
        meet_link=LINK, calendar_invite_id="invite-1", scheduled_start_time=when
    ).calendar_invite_id == "invite-1"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"meet_link": "x" * 513},
        {"meet_link": LINK, "unknown": 1},
        {"meet_link": LINK, "type": "other"},
        {"meet_link": LINK, "calendar_invite_id": "only-the-id"},
        {"meet_link": LINK, "scheduled_start_time": "2026-01-01T00:00:00Z"},
        {"meet_link": LINK, "calendar_invite_id": "i" * 257, "scheduled_start_time": "2026-01-01T00:00:00Z"},
        {"meet_link": LINK, "calendar_invite_id": "", "scheduled_start_time": "2026-01-01T00:00:00Z"},
    ],
)
def test_meeting_create_rejects_unbounded_or_unknown_input(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MeetingCreate(**payload)


async def test_create_meeting_accepts_the_portal_body(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{BASE}/", json={"meet_link": LINK}, headers=_headers())
    assert response.status_code == 201
    assert response.json()["process_state"] == "queued"


@pytest.mark.parametrize(
    "body",
    [
        {"meet_link": LINK, "created_by": "someone-else"},
        {"meet_link": "x" * 600},
        ["not", "an", "object"],
    ],
)
async def test_create_meeting_rejects_invalid_bodies_without_echoing_them(
    api_client: AsyncClient, body: Any
) -> None:
    response = await api_client.post(f"{BASE}/", json=body, headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"
    assert "someone-else" not in response.text and "created_by" not in response.text
    assert "xxxx" not in response.text


async def test_create_meeting_with_a_non_meet_link_is_a_generic_422(api_client: AsyncClient) -> None:
    response = await api_client.post(
        f"{BASE}/", json={"meet_link": "https://evil.example/secret-path"}, headers=_headers()
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert "evil" not in response.text


# --- other bodies, paths and queries -------------------------------------------------------------


async def test_rename_requires_a_bounded_title_and_forbids_extra_fields(
    api_client: AsyncClient, api_db_url: str
) -> None:
    [meeting_id] = await _seed(api_db_url, 1)
    url = f"{BASE}/{meeting_id}"

    assert (await api_client.patch(url, json={"title": "ok"}, headers=_headers())).status_code == 200
    assert (await api_client.patch(url, json={"title": "t" * 512}, headers=_headers())).status_code == 200
    for body in ({"title": "t" * 513}, {"title": ""}, {"title": "ok", "origin": "x"}):
        response = await api_client.patch(url, json=body, headers=_headers())
        assert response.status_code == 422, body
        assert response.json()["detail"] == "invalid_request"
        assert "tttt" not in response.text


@pytest.mark.parametrize("bad_id", ["x" * 65, "bad id", "semi;colon", "-leading-dash", "a" * 200])
async def test_malformed_meeting_ids_are_rejected_before_any_lookup(
    api_client: AsyncClient, bad_id: str
) -> None:
    for suffix in ("", "/transcript", "/playback", "/diarization", "/speaker-review"):
        response = await api_client.get(f"{BASE}/{bad_id}{suffix}", headers=_headers())
        assert response.status_code == 422, suffix
        assert response.json()["detail"] == "invalid_request"
        assert bad_id not in response.text


async def test_another_users_meeting_and_a_missing_one_are_indistinguishable(
    api_client: AsyncClient, api_db_url: str
) -> None:
    [foreign_id] = await _seed(api_db_url, 1, owner=OTHER)
    missing_id = str(uuid.uuid4())

    for suffix in ("", "/transcript", "/diarization", "/playback", "/speaker-review"):
        foreign = await api_client.get(f"{BASE}/{foreign_id}{suffix}", headers=_headers())
        missing = await api_client.get(f"{BASE}/{missing_id}{suffix}", headers=_headers())
        assert foreign.status_code == missing.status_code == 404, suffix
        assert foreign.json() == missing.json() == {"detail": "not_found"}
    assert (await api_client.delete(f"{BASE}/{foreign_id}", headers=_headers())).status_code == 404
    assert (await api_client.post(f"{BASE}/{foreign_id}/request-join", headers=_headers())).status_code == 404


@pytest.mark.parametrize("revision", ["0", "-1", "2147483648", "abc", "1.5"])
async def test_revision_ids_are_bounded(api_client: AsyncClient, api_db_url: str, revision: str) -> None:
    [meeting_id] = await _seed(api_db_url, 1)
    body = {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "k"}

    put = await api_client.put(
        f"{BASE}/{meeting_id}/speaker-review/revisions/{revision}/speakers/s-1",
        json=body, headers=_headers(),
    )
    get = await api_client.get(
        f"{BASE}/{meeting_id}/speaker-review", params={"revision_id": revision}, headers=_headers()
    )
    assert put.status_code == get.status_code == 422
    assert "input" not in put.text + get.text and "ctx" not in put.text + get.text


async def test_largest_revision_id_passes_validation(api_client: AsyncClient, api_db_url: str) -> None:
    [meeting_id] = await _seed(api_db_url, 1)
    response = await api_client.get(
        f"{BASE}/{meeting_id}/speaker-review", params={"revision_id": MAX_INT32}, headers=_headers()
    )
    assert response.status_code == 404  # valid id, no such review


async def test_disposition_body_forbids_extra_fields_and_bounds_values(
    api_client: AsyncClient, api_db_url: str
) -> None:
    [meeting_id] = await _seed(api_db_url, 1)
    url = f"{BASE}/{meeting_id}/speaker-review/revisions/1/speakers/s-1"
    good = {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "k"}
    for bad in (
        {**good, "extra": 1},
        {**good, "idempotency_key": "k" * 129},
        {**good, "label": "l" * 65},
        {**good, "expected_version": 0},
    ):
        response = await api_client.put(url, json=bad, headers=_headers())
        assert response.status_code == 422
        assert response.json()["detail"] == "invalid_request"


# --- pagination -------------------------------------------------------------------------------------


async def test_listing_defaults_to_the_whole_library_and_keeps_the_bare_list(
    api_client: AsyncClient, api_db_url: str
) -> None:
    await _seed(api_db_url, 5)
    await _seed(api_db_url, 3, owner=OTHER)

    response = await api_client.get(f"{BASE}/", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 5
    assert [item["title"] for item in body] == [f"Note {i}" for i in (4, 3, 2, 1, 0)]
    assert response.headers["X-Total-Count"] == "5"
    assert "Link" not in response.headers


async def test_pages_follow_the_link_header_without_overlap_or_gaps(
    api_client: AsyncClient, api_db_url: str
) -> None:
    await _seed(api_db_url, 5)

    first = await api_client.get(f"{BASE}/", params={"limit": 2}, headers=_headers())
    assert [m["title"] for m in first.json()] == ["Note 4", "Note 3"]
    assert first.headers["X-Total-Count"] == "5"
    link = first.headers["Link"]
    assert 'rel="next"' in link and "offset=2" in link and "limit=2" in link

    second = await api_client.get(f"{BASE}/", params={"limit": 2, "offset": 2}, headers=_headers())
    assert [m["title"] for m in second.json()] == ["Note 2", "Note 1"]
    assert "offset=4" in second.headers["Link"]

    last = await api_client.get(f"{BASE}/", params={"limit": 2, "offset": 4}, headers=_headers())
    assert [m["title"] for m in last.json()] == ["Note 0"]
    assert "Link" not in last.headers


async def test_offset_past_the_end_is_an_empty_page_that_still_reports_the_total(
    api_client: AsyncClient, api_db_url: str
) -> None:
    await _seed(api_db_url, 3)
    response = await api_client.get(f"{BASE}/", params={"offset": 10}, headers=_headers())
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "3"
    assert "Link" not in response.headers


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"limit": -1}, {"limit": "many"}, {"offset": -1}, {"offset": 1_000_001}],
)
async def test_out_of_range_paging_parameters_are_rejected(
    api_client: AsyncClient, params: dict[str, Any]
) -> None:
    response = await api_client.get(f"{BASE}/", params=params, headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"
    assert "many" not in response.text


async def test_the_maximum_page_size_is_accepted(api_client: AsyncClient, api_db_url: str) -> None:
    await _seed(api_db_url, 2)
    assert (await api_client.get(f"{BASE}/", params={"limit": 500}, headers=_headers())).status_code == 200


# --- signed link lifetime -----------------------------------------------------------------------------


def test_signed_link_lifetime_defaults_to_fifteen_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNED_URL_TTL_SECONDS", raising=False)
    assert signed_url_ttl_seconds() == DEFAULT_SIGNED_URL_TTL_SECONDS == 900


@pytest.mark.parametrize(("raw", "expected"), [("60", 60), ("3600", 3600), ("1200", 1200), ("", 900)])
def test_signed_link_lifetime_accepts_the_documented_range(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    monkeypatch.setenv("SIGNED_URL_TTL_SECONDS", raw)
    assert signed_url_ttl_seconds() == expected


@pytest.mark.parametrize("raw", ["59", "3601", "0", "-5", "ten", "1.5"])
def test_signed_link_lifetime_outside_the_range_raises(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SIGNED_URL_TTL_SECONDS", raw)
    with pytest.raises(ValueError):
        signed_url_ttl_seconds()


def test_playback_link_lifetime_defaults_to_four_hours_to_outlast_a_long_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYBACK_URL_TTL_SECONDS", raising=False)
    monkeypatch.setenv("SIGNED_URL_TTL_SECONDS", "60")  # the two settings are independent
    assert playback_url_ttl_seconds() == DEFAULT_PLAYBACK_URL_TTL_SECONDS == 14_400
    assert playback_url_ttl_seconds() > 94 * 60  # the longest recording measured so far


@pytest.mark.parametrize(
    ("raw", "expected"), [("300", 300), ("43200", 43200), ("7200", 7200), ("", 14_400)]
)
def test_playback_link_lifetime_accepts_the_documented_range(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    monkeypatch.setenv("PLAYBACK_URL_TTL_SECONDS", raw)
    assert playback_url_ttl_seconds() == expected


@pytest.mark.parametrize("raw", ["299", "43201", "0", "-5", "four", "1.5"])
def test_playback_link_lifetime_outside_the_range_raises(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("PLAYBACK_URL_TTL_SECONDS", raw)
    with pytest.raises(ValueError):
        playback_url_ttl_seconds()
