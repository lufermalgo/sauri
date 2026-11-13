"""Portal processing projection: real core stages, current revision and owner boundary."""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Diarization, Meeting, MeetingProcessingClaim, SpeechTurn, Transcript
from app.meetings.processing import processing_snapshot


def meeting() -> Meeting:
    return Meeting(
        id="processing-meeting", created_by="owner", process_state="transcribing",
        origin="manual", created_at=datetime.now(UTC),
    )


async def artifacts(session: AsyncSession, m: Meeting, state: str) -> Diarization:
    session.add(Transcript(
        id="transcript", meeting_id=m.id, language="es", provider="local",
        supports_turns=True, created_at=datetime.now(UTC),
    ))
    await session.flush()
    session.add(SpeechTurn(
        id="turn", transcript_id="transcript", text="Private synthetic text",
        start_ms=0, end_ms=1000, sequence=1,
    ))
    d = Diarization(
        id="diarization", meeting_id=m.id, transcript_id="transcript",
        processing_revision=1, diarization_state=state,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(d)
    await session.flush()
    return d


@pytest.mark.asyncio
async def test_waiting_claim_then_transcribing_then_speakers_then_ready(db_session: AsyncSession) -> None:
    m = meeting()
    db_session.add(m)
    claim = MeetingProcessingClaim(meeting_id=m.id, generation=1)
    db_session.add(claim)
    await db_session.flush()
    snapshot = await processing_snapshot(db_session, m)
    assert snapshot["stages"][1]["state"] == "pending"
    assert not snapshot["ready"]
    claim.claim_kind, claim.claim_id = "transcription", "job"
    await db_session.flush()
    assert (await processing_snapshot(db_session, m))["stages"][1]["state"] == "active"
    await artifacts(db_session, m, "pending")
    m.process_state = "completed"
    await db_session.flush()
    snapshot = await processing_snapshot(db_session, m)
    assert snapshot["stages"][1]["state"] == "completed"
    assert snapshot["stages"][2]["state"] == "pending"
    assert not snapshot["ready"]
    d = await db_session.get(Diarization, "diarization")
    assert d is not None
    for state, visible in [("in_progress", "active"), ("failed", "failed"), ("completed", "completed")]:
        d.diarization_state = state
        await db_session.flush()
        snapshot = await processing_snapshot(db_session, m)
        assert snapshot["stages"][2]["state"] == visible
        assert snapshot["failed"] == (state == "failed")
        assert snapshot["ready"] == (state == "completed")
    assert "Private synthetic text" not in str(snapshot)
    assert all(stage["state"] == "unavailable" for stage in snapshot["stages"][:1])


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "in_progress", "failed", "not_reconstructible"])
async def test_latest_revision_overrides_completed_attempt(db_session: AsyncSession, state: str) -> None:
    m = meeting()
    m.process_state = "completed"
    db_session.add(m)
    await db_session.flush()
    await artifacts(db_session, m, "completed")
    db_session.add(Diarization(
        id="new-attempt", meeting_id=m.id, transcript_id="transcript",
        processing_revision=2, diarization_state=state,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    ))
    await db_session.flush()
    snapshot = await processing_snapshot(db_session, m)
    assert snapshot["execution"]["diarization_revision"] == 2
    assert not snapshot["ready"]


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [
    "no_diarization", "no_timing", "no_turns", "expired_transcript",
    "legacy", "recovery", "meeting_failed", "expired_claim",
])
async def test_partial_or_recovering_never_ready(db_session: AsyncSession, partial: str) -> None:
    m = meeting()
    m.process_state = "completed"
    db_session.add(m)
    await db_session.flush()
    d = await artifacts(db_session, m, "completed")
    if partial == "no_diarization":
        await db_session.delete(d)
    elif partial == "no_timing":
        turn = await db_session.get(SpeechTurn, "turn")
        assert turn is not None
        # The schema forbids NULL; an invalid interval must also block readiness.
        turn.end_ms = 0
    elif partial == "no_turns":
        turn = await db_session.get(SpeechTurn, "turn")
        assert turn is not None
        await db_session.delete(turn)
    elif partial == "expired_transcript":
        transcript = await db_session.get(Transcript, "transcript")
        assert transcript is not None
        transcript.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif partial == "legacy":
        d.is_legacy = True
    elif partial == "recovery":
        db_session.add(MeetingProcessingClaim(meeting_id=m.id, generation=3, claim_kind="recovery", claim_id="op"))
    elif partial == "expired_claim":
        m.process_state = "transcribing"
        db_session.add(MeetingProcessingClaim(
            meeting_id=m.id, generation=3, claim_kind="transcription", claim_id="old-job",
            claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        ))
    else:
        m.process_state = "failed"
    await db_session.flush()
    assert not (await processing_snapshot(db_session, m))["ready"]


def headers(user: str, sales: bool = True) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user, 'synthetic@example.test', 'Test', sales)}"}


@pytest.mark.asyncio
async def test_endpoint_authorized_read_does_not_create_work(api_client: AsyncClient, api_db_url: str) -> None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            session.add(meeting())
        path = "/api/v1/meetings/processing-meeting/processing"
        for _ in range(2):
            response = await api_client.get(path, headers=headers("owner"))
            assert response.status_code == 200
            assert not response.json()["ready"]
        assert (await api_client.get(path)).status_code == 401
        assert (await api_client.get(path, headers=headers("owner", False))).status_code == 403
        denied = await api_client.get(path, headers=headers("stranger"))
        missing = await api_client.get("/api/v1/meetings/missing/processing", headers=headers("stranger"))
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json()
        async with factory() as session:
            m = await session.get(Meeting, "processing-meeting")
            assert m is not None and m.process_state == "transcribing"
            assert (await session.scalars(select(MeetingProcessingClaim))).all() == []
            assert (await session.scalars(select(Transcript))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["engine_failure", "could_not_join", "meeting_cancelled", None])
async def test_failure_does_not_invent_an_affected_stage(db_session: AsyncSession, cause: str | None) -> None:
    m = meeting()
    m.process_state, m.failure_cause = "failed", cause
    db_session.add(m)
    await db_session.flush()
    snapshot = await processing_snapshot(db_session, m)
    assert snapshot["failed"] and not snapshot["ready"]
    assert snapshot["stages"][1]["state"] == ("failed" if cause == "engine_failure" else "unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", ["pending", "in_progress", "failed", "not_reconstructible", "completed"])
async def test_multirevision_result_read_preserves_completed_and_current_attempt_separately(
    api_client: AsyncClient, api_db_url: str, latest: str,
) -> None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            m = meeting()
            m.process_state = "completed"
            session.add(m)
            await session.flush()
            await artifacts(session, m, "completed")
            session.add(Diarization(
                id="new-attempt", meeting_id=m.id, transcript_id="transcript", processing_revision=2,
                diarization_state=latest, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            ))
        path = "/api/v1/meetings/processing-meeting"
        result = await api_client.get(path + "/diarization", headers=headers("owner"))
        status = await api_client.get(path + "/processing", headers=headers("owner"))
        assert result.status_code == status.status_code == 200
        assert result.json()["processing_revision"] == (2 if latest == "completed" else 1)
        assert result.json()["latest_attempt"]["processing_revision"] == 2
        assert result.json()["latest_attempt"]["diarization_state"] == latest
        assert status.json()["execution"]["diarization_revision"] == 2
        assert status.json()["ready"] == (latest == "completed")
    finally:
        await engine.dispose()
