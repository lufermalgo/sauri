"""Passages use the latest completed speaker assignments, without dropping unmatched turns."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.infra.models import Diarization, Speaker, SpeakerAssignment, SpeechTurn, Transcript
from app.summaries.repository import transcript_passages
from tests.summaries.test_summary_api import ApiFixture
from tests.summaries.test_summary_api import summary_api as summary_api


async def test_latest_complete_revision_and_unknown_speaker(summary_api: ApiFixture) -> None:
    _, factory, _, _, meeting, _, _ = summary_api
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting))
        assert transcript is not None
        session.add_all(
            [
                SpeechTurn(
                    id="t1", transcript_id=transcript.id, text="First synthetic", start_ms=0, end_ms=1000, sequence=1
                ),
                SpeechTurn(
                    id="t2",
                    transcript_id=transcript.id,
                    text="Unknown synthetic",
                    start_ms=70_000,
                    end_ms=71_000,
                    sequence=2,
                ),
            ]
        )
        for revision, state in ((1, "completed"), (2, "completed"), (3, "in_progress")):
            session.add(
                Diarization(
                    id=f"d{revision}",
                    meeting_id=meeting,
                    transcript_id=transcript.id,
                    processing_revision=revision,
                    diarization_state=state,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                Speaker(
                    id=f"s{revision}",
                    diarization_id=f"d{revision}",
                    raw_label="raw",
                    label=f"Speaker {revision}",
                    sequence=revision,
                )
            )
            await session.flush()
            session.add(
                SpeakerAssignment(
                    id=f"a{revision}", diarization_id=f"d{revision}", turn_id="t1", speaker_id=f"s{revision}"
                )
            )
        await session.flush()
        passages = await transcript_passages(session, transcript.id)
        assert [t.text for p in passages for t in p.turns] == ["First synthetic", "Unknown synthetic"]
        assert passages[0].turns[0].speaker == "Speaker 2"
        assert passages[1].turns[0].speaker == "Speaker ?"
