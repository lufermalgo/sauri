"""GET /summary shows the owner's chosen speaker names without touching what is stored (#1190)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Diarization,
    Meeting,
    MeetingSummary,
    Speaker,
    SpeakerReview,
    SpeakerReviewItem,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
)
from tests.summaries.test_summary_api import ApiFixture, _headers
from tests.summaries.test_summary_api import summary_api as summary_api

NOW = datetime.now(UTC).replace(microsecond=0)
BLOCKS = {
    "schema_version": 2,
    "key_points": [
        {
            "title": "Speaker 1 opens",
            "items": [{"text": "Speaker 2 objects", "sub_items": ["Speaker 1 replies", "speaker 12 is not 1"]}],
            "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}],
        }
    ],
    "conclusion": "Speaker 2 and Speaker 1 agree.",
}
SPANISH_BLOCKS = json.loads(json.dumps(BLOCKS).replace("Speaker", "Hablante"))  # spanish-sample-data


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    meeting: str,
    *,
    names: dict[int, str | None],
    language: str = "en",
    payload: object = BLOCKS,
    diarized_at: datetime = NOW - timedelta(minutes=10),
    summary_at: datetime = NOW,
    started_at: datetime | None = None,
    revision: int = 1,
) -> None:
    """One completed diarization with speakers 1..n (named per ``names``) and one stored summary."""
    async with factory() as session, session.begin():
        transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting))
        assert transcript is not None
        transcript.language = language
        diarization_id = f"dia-{revision}"
        session.add(
            Diarization(
                id=diarization_id, meeting_id=meeting, transcript_id=transcript.id, processing_revision=revision,
                diarization_state="completed", created_at=diarized_at, updated_at=diarized_at,
            )
        )
        review = SpeakerReview(
            id=f"rev-{revision}", meeting_id=meeting, processing_revision=revision, status="pending", created_at=NOW
        )
        session.add(review)
        await session.flush()
        for number, chosen in names.items():
            session.add(
                Speaker(
                    id=f"spk-{revision}-{number}", diarization_id=diarization_id, raw_label=f"raw{number}",
                    label=f"Speaker {number}", sequence=number,
                )
            )
            await session.flush()
            session.add(
                SpeakerReviewItem(
                    id=f"item-{revision}-{number}", review_id=review.id, speaker_key=f"spk-{revision}-{number}",
                    current_label=f"Speaker {number}", chosen_label=chosen,
                )
            )
        template_id = await _template_id(session, meeting)
        session.add(
            SummaryRequestOutbox(
                event_id="evt-1", meeting_id=meeting, transcript_id=transcript.id, template_id=template_id,
                template_version=1, instructions_snapshot="x", generation=1, status="succeeded",
                requested_at=summary_at, started_at=started_at, finished_at=summary_at,
            )
        )
        await session.flush()
        session.add(
            MeetingSummary(
                id="sum-1", event_id="evt-1", meeting_id=meeting, transcript_id=transcript.id, template_id=template_id,
                template_version=1, topic="Speaker 1 chairs; Speaker 2 presents; Speaker 3 listens.",
                key_points_json=json.dumps(payload), generation=1, created_at=summary_at, updated_at=summary_at,
            )
        )


async def _template_id(session: AsyncSession, meeting: str) -> str:
    owner = await session.scalar(select(Meeting.created_by).where(Meeting.id == meeting))
    template = await session.scalar(select(SummaryTemplate.id).where(SummaryTemplate.owner_user_id == owner))
    assert template is not None
    return template


async def _get(fixture: ApiFixture) -> dict[str, object]:
    client, _, owner, _, meeting, _, _ = fixture
    response = await client.get(f"/api/v1/meetings/{meeting}/summary", headers=_headers(owner))
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


@pytest.mark.asyncio
async def test_only_the_named_speaker_is_replaced_everywhere(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Ana", 2: None, 3: "  "})
    body = await _get(summary_api)
    assert body["topic"] == "Ana chairs; Speaker 2 presents; Speaker 3 listens."
    assert body["conclusion"] == "Speaker 2 and Ana agree."
    assert body["key_points"] == [
        {
            "title": "Ana opens",
            "items": [{"text": "Speaker 2 objects", "sub_items": ["Ana replies", "speaker 12 is not 1"]}],
            "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}],
        }
    ]


@pytest.mark.asyncio
async def test_renaming_changes_the_next_read_and_nothing_stored_changes(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Ana", 2: "Luis"})
    first = await _get(summary_api)
    assert first["conclusion"] == "Luis and Ana agree."
    async with factory() as session, session.begin():
        item = await session.get(SpeakerReviewItem, "item-1-1")
        assert item is not None
        item.chosen_label = r"Ana \1 & <b>"
    body = await _get(summary_api)
    assert body["conclusion"] == r"Luis and Ana \1 & <b> agree."
    async with factory() as session:
        stored = await session.get(MeetingSummary, "sum-1")
        assert stored is not None
        assert stored.topic == "Speaker 1 chairs; Speaker 2 presents; Speaker 3 listens."
        assert json.loads(stored.key_points_json) == BLOCKS
        assert (stored.generation, stored.updated_at.replace(tzinfo=None)) == (1, NOW.replace(tzinfo=None))
    assert (body["generation"], body["updated_at"]) == (first["generation"], first["updated_at"])


@pytest.mark.asyncio
async def test_spanish_transcript_uses_the_spanish_label(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Ana", 2: "Luis"}, language="es-CO", payload=SPANISH_BLOCKS)
    body = await _get(summary_api)
    assert body["conclusion"] == "Luis and Ana agree."
    assert body["key_points"] == [
        {
            "title": "Ana opens",
            "items": [{"text": "Luis objects", "sub_items": ["Ana replies", "speaker 12 is not 1"]}],
            "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}],
        }
    ]


@pytest.mark.asyncio
async def test_english_label_in_a_spanish_transcript_is_left_alone(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Ana"}, language="es")
    assert (await _get(summary_api))["conclusion"] == "Speaker 2 and Speaker 1 agree."


@pytest.mark.asyncio
async def test_summary_older_than_the_latest_diarization_is_not_renamed(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Ana", 2: "Luis"}, diarized_at=NOW + timedelta(minutes=5))
    body = await _get(summary_api)
    assert body["conclusion"] == "Speaker 2 and Speaker 1 agree."
    assert body["topic"] == "Speaker 1 chairs; Speaker 2 presents; Speaker 3 listens."


@pytest.mark.asyncio
async def test_diarization_finished_while_the_summary_was_running_is_not_renamed(summary_api: ApiFixture) -> None:
    # Taken by the worker before the new numbering existed, written after it: the passages may be stale.
    _, factory, _, _, meeting, _, _ = summary_api
    started = NOW - timedelta(minutes=2)
    await _seed(factory, meeting, names={1: "Ana"}, diarized_at=NOW - timedelta(minutes=1), started_at=started)
    assert (await _get(summary_api))["conclusion"] == "Speaker 2 and Speaker 1 agree."


@pytest.mark.asyncio
async def test_diarization_finished_before_the_summary_started_is_renamed(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    started = NOW - timedelta(minutes=2)
    await _seed(factory, meeting, names={1: "Ana"}, diarized_at=NOW - timedelta(minutes=3), started_at=started)
    assert (await _get(summary_api))["conclusion"] == "Speaker 2 and Ana agree."


@pytest.mark.asyncio
async def test_names_come_from_the_latest_completed_revision_only(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={1: "Old Ana", 2: "Old Luis"}, revision=1, diarized_at=NOW - timedelta(hours=1))
    async with factory() as session, session.begin():
        transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting))
        assert transcript is not None
        session.add(
            Diarization(
                id="dia-2", meeting_id=meeting, transcript_id=transcript.id, processing_revision=2,
                diarization_state="completed", created_at=NOW - timedelta(minutes=30),
                updated_at=NOW - timedelta(minutes=30),
            )
        )
        session.add(
            SpeakerReview(id="rev-2", meeting_id=meeting, processing_revision=2, status="pending", created_at=NOW)
        )
        await session.flush()
        session.add(Speaker(id="spk-2-2", diarization_id="dia-2", raw_label="r", label="Speaker 2", sequence=2))
        await session.flush()
        session.add(
            SpeakerReviewItem(
                id="item-2-2", review_id="rev-2", speaker_key="spk-2-2", current_label="Speaker 2",
                chosen_label="New Luis",
            )
        )
    assert (await _get(summary_api))["conclusion"] == "New Luis and Speaker 1 agree."


@pytest.mark.asyncio
async def test_summary_without_any_diarization_is_unchanged(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    await _seed(factory, meeting, names={})
    async with factory() as session, session.begin():
        dia = await session.get(Diarization, "dia-1")
        assert dia is not None
        dia.diarization_state = "failed"
    assert (await _get(summary_api))["conclusion"] == "Speaker 2 and Speaker 1 agree."
