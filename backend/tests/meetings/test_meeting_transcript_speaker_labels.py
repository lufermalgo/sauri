"""T-15 RED contract for owner-safe polling and revision-correct transcript labels."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    Transcript,
)

OWNER_ID = "speaker-label-owner"
OTHER_OWNER_ID = "speaker-label-other-owner"


def _auth_header(owner_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(owner_id, f"{owner_id}@sauri.local", "Synthetic Reviewer", True)
    return {"Authorization": f"Bearer {token}"}


async def _persist_meeting(api_db_url: str, owner_id: str = OWNER_ID) -> str:
    meeting_id = str(uuid.uuid4())
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="transcribing",
                failure_cause=None,
                created_by=owner_id,
                created_at=datetime.now(UTC),
            )
        )
    await engine.dispose()
    return meeting_id


async def test_foreign_owner_cannot_poll_meeting_state(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id = await _persist_meeting(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}", headers=_auth_header(OTHER_OWNER_ID)
    )

    assert response.status_code == 404
    assert meeting_id not in response.text


@pytest.mark.asyncio
async def test_transcript_uses_active_revision_speaker_join_and_effective_labels(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id = await _persist_meeting(api_db_url)
    transcript_id = str(uuid.uuid4())
    diarization_id, old_diarization_id = str(uuid.uuid4()), str(uuid.uuid4())
    speaker_ids = [str(uuid.uuid4()) for _ in range(4)]
    old_speaker_id = str(uuid.uuid4())
    turn_ids = [str(uuid.uuid4()) for _ in range(4)]
    old_review_id, active_review_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)

    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session, session.begin():
        session.add(
            Transcript(
                id=transcript_id,
                meeting_id=meeting_id,
                language="es-CO",
                provider="local",
                supports_turns=True,
                expires_at=None,
                created_at=now,
            )
        )
        session.add(
            Diarization(
                id=diarization_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                provider="local",
                speaker_count=4,
                processing_revision=2,
                diarization_state="completed",
                failure_cause=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Diarization(
                id=old_diarization_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                provider="local",
                speaker_count=1,
                processing_revision=1,
                diarization_state="completed",
                failure_cause=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Speaker(
                id=old_speaker_id,
                diarization_id=old_diarization_id,
                raw_label="SPEAKER_0",
                label="Speaker 1",
                sequence=1,
            )
        )
        session.add_all(
            [
                Speaker(
                    id=speaker_id,
                    diarization_id=diarization_id,
                    raw_label=f"SPEAKER_{index}",
                    label=f"Speaker {index}",
                    sequence=index,
                )
                for index, speaker_id in enumerate(speaker_ids, start=1)
            ]
        )
        session.add_all(
            [
                SpeechTurn(
                    id=turn_id,
                    transcript_id=transcript_id,
                    text=text,
                    start_ms=index * 1000,
                    end_ms=(index + 1) * 1000,
                    sequence=index,
                )
                for index, (turn_id, text) in enumerate(
                    zip(
                        turn_ids,
                        ("Hola exacto", "Texto sin cambios", "Hasta luego", "Texto sin review"),
                        strict=True,
                    )
                )
            ]
        )
        session.add_all(
            [
                SpeakerAssignment(
                    id=str(uuid.uuid4()),
                    diarization_id=diarization_id,
                    turn_id=turn_id,
                    speaker_id=speaker_id,
                )
                for turn_id, speaker_id in zip(
                    turn_ids, (speaker_ids[2], speaker_ids[0], speaker_ids[3], speaker_ids[1]), strict=True
                )
            ]
        )
        session.add_all(
            [
                SpeakerAssignment(
                    id=str(uuid.uuid4()),
                    diarization_id=old_diarization_id,
                    turn_id=turn_id,
                    speaker_id=old_speaker_id,
                )
                for turn_id in turn_ids
            ]
        )
        session.add_all(
            [
                SpeakerReview(
                    id=old_review_id,
                    meeting_id=meeting_id,
                    processing_revision=1,
                    status="complete",
                    created_at=now,
                ),
                SpeakerReview(
                    id=active_review_id,
                    meeting_id=meeting_id,
                    processing_revision=2,
                    status="pending",
                    created_at=now,
                ),
            ]
        )
        session.add_all(
            [
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=old_review_id,
                    speaker_key=old_speaker_id,
                    current_label="Stale revision name",
                    disposition="named",
                    chosen_label="Stale revision name",
                    attribution_state="attributed",
                    version=2,
                ),
                # A stale item can reuse an active key; key-only lookups must not win.
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=old_review_id,
                    speaker_key=speaker_ids[0],
                    current_label="Stale colliding label",
                    disposition="named",
                    chosen_label="Stale colliding label",
                    attribution_state="attributed",
                    version=2,
                ),
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=active_review_id,
                    speaker_key=speaker_ids[0],
                    current_label="Speaker 1",
                    disposition="corrected",
                    chosen_label="Alice corrected",
                    attribution_state="attributed",
                    version=2,
                ),
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=active_review_id,
                    speaker_key=speaker_ids[1],
                    current_label="Speaker 2 (review pending)",
                    disposition=None,
                    chosen_label=None,
                    attribution_state="uncertain",
                    version=1,
                ),
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=active_review_id,
                    speaker_key=speaker_ids[2],
                    current_label="Speaker 3",
                    disposition="named",
                    chosen_label="Bob named",
                    attribution_state="attributed",
                    version=2,
                ),
            ]
        )
    await engine.dispose()

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/transcript", headers=_auth_header()
    )

    assert response.status_code == 200
    segments = response.json()["segments"]
    assert [segment["id"] for segment in segments] == turn_ids
    assert [segment["text"] for segment in segments] == [
        "Hola exacto",
        "Texto sin cambios",
        "Hasta luego",
        "Texto sin review",
    ]
    assert [segment["speaker_label"] for segment in segments] == [
        "Bob named",
        "Alice corrected",
        "Speaker 4",
        "Speaker 2 (review pending)",
    ]
