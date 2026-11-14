"""T-12 persisted speaker-review resume contract tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import AccessLog, Diarization, Meeting, SpeakerReview, SpeakerReviewItem, Transcript

OWNER_ID = "resume-owner"
OTHER_OWNER_ID = "resume-other-owner"


def _auth_header(owner_id: str = OWNER_ID, is_sales: bool = True) -> dict[str, str]:
    token = create_token(
        owner_id, f"{owner_id}@sauri.local", "Synthetic Reviewer", is_sales
    )
    return {"Authorization": f"Bearer {token}"}


async def _persist_review(
    api_db_url: str,
    dispositions: tuple[str | None, ...] = ("named", None),
) -> tuple[str, str]:
    engine = create_async_engine(api_db_url, echo=False)
    meeting_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=OWNER_ID,
                created_at=now,
            )
        )
        session.add(Transcript(
            id=f"transcript-{meeting_id}", meeting_id=meeting_id, language="es",
            provider="synthetic", supports_turns=True, created_at=datetime.now(UTC),
        ))
        session.add(Diarization(
            id=f"diarization-{meeting_id}", meeting_id=meeting_id,
            transcript_id=f"transcript-{meeting_id}", processing_revision=1,
            diarization_state="completed", speaker_count=2,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ))
        session.add(
            SpeakerReview(
                id=review_id,
                meeting_id=meeting_id,
                processing_revision=1,
                status="complete" if all(dispositions) else "pending",
                created_at=now,
            )
        )
        session.add_all(
            [
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    speaker_key=f"speaker-{index}",
                    current_label=f"Speaker {index}",
                    disposition=disposition,
                    chosen_label="Synthetic Alice" if disposition == "named" else None,
                    attribution_state="uncertain",
                    version=2 if disposition else 1,
                )
                for index, disposition in enumerate(dispositions, start=1)
            ]
        )
    await engine.dispose()
    return meeting_id, review_id


@pytest.mark.asyncio
async def test_pending_review_reload_includes_disposed_and_pending_items(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, review_id = await _persist_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review", headers=_auth_header()
    )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": review_id,
        "revision_id": 1,
        "status": "pending",
        "labels_by_speaker_id": {"speaker-1": "Synthetic Alice", "speaker-2": "Speaker 2"},
        "items": [
            {
                "speaker_id": "speaker-1",
                "current_label": "Speaker 1",
                "disposition": "named",
                "attribution_state": "uncertain",
                "version": 2,
            },
            {
                "speaker_id": "speaker-2",
                "current_label": "Speaker 2",
                "disposition": None,
                "attribution_state": "uncertain",
                "version": 1,
            }
        ],
    }


@pytest.mark.asyncio
async def test_completed_review_reload_returns_no_outstanding_items(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, review_id = await _persist_review(api_db_url, ("named", "confirmed"))

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review", headers=_auth_header()
    )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": review_id,
        "revision_id": 1,
        "status": "complete",
        "labels_by_speaker_id": {"speaker-1": "Synthetic Alice", "speaker-2": "Speaker 2"},
        "items": [
            {"speaker_id": "speaker-1", "current_label": "Speaker 1", "disposition": "named",
             "attribution_state": "uncertain", "version": 2},
            {"speaker_id": "speaker-2", "current_label": "Speaker 2", "disposition": "confirmed",
             "attribution_state": "uncertain", "version": 2},
        ],
    }


@pytest.mark.asyncio
async def test_empty_review_status_uses_approved_derived_completion_rule(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, review_id = await _persist_review(api_db_url, ())

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review", headers=_auth_header()
    )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": review_id,
        "revision_id": 1,
        "status": "complete",
        "labels_by_speaker_id": {},
        "items": [],
    }


@pytest.mark.asyncio
async def test_review_reload_does_not_expose_another_owners_review(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, _ = await _persist_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(OTHER_OWNER_ID),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_non_sales_owner_cannot_read_speaker_review_and_denial_is_audited(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, _ = await _persist_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(OWNER_ID, is_sales=False),
    )

    assert response.status_code == 403
    assert "items" not in response.json()

    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(AccessLog).where(AccessLog.user_id == OWNER_ID)
        )
        records = result.scalars().all()
    await engine.dispose()

    assert len(records) == 1
    assert records[0].result == "denied"
    assert records[0].resource == (
        f"GET /api/v1/meetings/{meeting_id}/speaker-review"
    )
