"""Ingestion decides when a recording was made, from the best evidence the sender gave."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion, resolve_recorded_at

OWNER = "synthetic-owner"


def _data(**overrides: Any) -> IngestionData:
    base: dict[str, Any] = {
        "meeting_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "capture_origin": "web_upload",
        "duration_seconds": 60,
        "video_presence": "absent",
    }
    return IngestionData(**{**base, **overrides})


def _ago(**delta: float) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


# --- Validation of the sender's date -------------------------------------------------------------


def test_a_plausible_iso_date_is_accepted_and_normalised_to_utc() -> None:
    data = _data(recorded_at="2025-03-04T10:00:00-05:00")
    assert data.recorded_at == datetime(2025, 3, 4, 15, 0, tzinfo=UTC)
    assert data.recorded_at is not None and data.recorded_at.utcoffset() == timedelta(0)


def test_a_naive_date_is_read_as_utc() -> None:
    assert _data(recorded_at="2025-03-04T10:00:00").recorded_at == datetime(2025, 3, 4, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        "1989-12-31T23:59:59Z",  # before 1990 (a zeroed or epoch file date)
        "1970-01-01T00:00:00Z",
        None,
        "not a date",
        "",
        12345,
    ],
)
def test_an_implausible_or_malformed_date_is_dropped_not_rejected(value: object) -> None:
    assert _data(recorded_at=value).recorded_at is None


def test_a_date_in_the_future_is_dropped_but_a_small_clock_skew_is_tolerated() -> None:
    assert _data(recorded_at=(_ago() + timedelta(days=2)).isoformat()).recorded_at is None
    skewed = _ago() + timedelta(minutes=5)
    assert _data(recorded_at=skewed.isoformat()).recorded_at == skewed


def test_the_first_day_of_1990_is_the_earliest_accepted_date() -> None:
    assert _data(recorded_at="1990-01-01T00:00:00Z").recorded_at == datetime(1990, 1, 1, tzinfo=UTC)


# --- Which source is chosen ----------------------------------------------------------------------


def test_extension_capture_start_is_the_capture_source() -> None:
    started = _ago(hours=2).replace(microsecond=0)
    moment, source = resolve_recorded_at(
        _data(capture_origin="chrome_extension", recorded_at=started.isoformat()), datetime.now(UTC)
    )
    assert (moment, source) == (started, "capture")


def test_an_older_extension_without_a_start_uses_its_consent_notice_time() -> None:
    noticed = _ago(minutes=50).replace(microsecond=0)
    moment, source = resolve_recorded_at(
        _data(capture_origin="chrome_extension", notice_issued_at=noticed.isoformat()), datetime.now(UTC)
    )
    assert (moment, source) == (noticed, "capture")


def test_an_extension_with_nothing_usable_falls_back_to_receipt() -> None:
    now = datetime.now(UTC)
    moment, source = resolve_recorded_at(
        _data(capture_origin="chrome_extension", notice_issued_at="1970-01-01T00:00:00+00:00"), now
    )
    assert (moment, source) == (now, "received")


def test_a_web_upload_uses_the_browser_file_date() -> None:
    modified = _ago(days=200).replace(microsecond=0)
    moment, source = resolve_recorded_at(_data(recorded_at=modified.isoformat()), datetime.now(UTC))
    assert (moment, source) == (modified, "file_modified")


def test_a_web_upload_never_takes_the_notice_time_as_a_recording_date() -> None:
    now = datetime.now(UTC)
    _, source = resolve_recorded_at(_data(notice_issued_at=now.isoformat()), now)
    assert source == "received"


def test_a_web_upload_without_a_usable_date_falls_back_to_receipt() -> None:
    now = datetime.now(UTC)
    assert resolve_recorded_at(_data(recorded_at="1970-01-01T00:00:00Z"), now) == (now, "received")


# --- What is stored ------------------------------------------------------------------------------


async def _ingest(factory: async_sessionmaker[AsyncSession], data: IngestionData) -> Meeting:
    async with factory() as session, session.begin():
        await process_ingestion(session, data, "audio/ref", None, OWNER)
    async with factory() as session:
        meeting = await session.get(Meeting, data.meeting_id)
    assert meeting is not None
    return meeting


@pytest.mark.asyncio
async def test_a_new_upload_stores_the_file_date_apart_from_the_receipt_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    modified = _ago(days=400).replace(microsecond=0)
    meeting = await _ingest(session_factory, _data(recorded_at=modified.isoformat()))

    assert meeting.recorded_at_source == "file_modified"
    assert meeting.recorded_at is not None
    assert meeting.recorded_at.replace(tzinfo=UTC) == modified
    assert meeting.created_at.replace(tzinfo=UTC) > modified + timedelta(days=300)


@pytest.mark.asyncio
async def test_an_upload_without_a_date_is_recorded_as_received(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting = await _ingest(session_factory, _data())
    assert meeting.recorded_at_source == "received"
    assert meeting.recorded_at == meeting.created_at


@pytest.mark.asyncio
async def test_an_extension_recording_improves_the_meeting_registered_before_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = str(uuid.uuid4())
    registered = _ago(hours=3)
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij", origin="manual",
            process_state="recording", created_by=OWNER, created_at=registered,
            recorded_at=registered, recorded_at_source="received",
        ))
    started = _ago(hours=2, minutes=30).replace(microsecond=0)

    meeting = await _ingest(session_factory, _data(
        meeting_id=meeting_id, capture_origin="chrome_extension", recorded_at=started.isoformat(),
    ))

    assert meeting.recorded_at_source == "capture"
    assert meeting.recorded_at is not None and meeting.recorded_at.replace(tzinfo=UTC) == started


@pytest.mark.asyncio
async def test_a_weaker_source_never_replaces_a_stronger_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = str(uuid.uuid4())
    captured = _ago(hours=5).replace(microsecond=0)
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="recording",
            created_by=OWNER, created_at=_ago(hours=4), recorded_at=captured, recorded_at_source="capture",
        ))

    meeting = await _ingest(session_factory, _data(meeting_id=meeting_id))  # nothing usable: "received"

    assert meeting.recorded_at_source == "capture"
    assert meeting.recorded_at is not None and meeting.recorded_at.replace(tzinfo=UTC) == captured
