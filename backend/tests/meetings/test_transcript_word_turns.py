"""Attributed word turns in GET /transcript and latest revision in GET /diarization (U3.4, #923).

Runs against a real PostgreSQL: each module run creates a throwaway database next
to the one in SAURI_QA_POSTGRES_URL (a disposable ``sauri_qa`` database), builds
the schema with ``alembic upgrade head`` and drops the database afterwards.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.auth.token import create_token
from app.infra.models import (
    AccessLog,
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
    TranscriptWord,
    WordSpeakerAssignment,
)

BACKEND = Path(__file__).resolve().parents[2]
OWNER = "synthetic-owner"

Factory = async_sessionmaker[AsyncSession]


def _asyncpg_args(url: str) -> dict[str, str | int]:
    parsed = make_url(url)
    args: dict[str, str | int] = {"user": parsed.username or "", "database": parsed.database or ""}
    if parsed.password is not None:
        args["password"] = parsed.password
    if parsed.host is not None:
        args["host"] = parsed.host
    if parsed.port is not None:
        args["port"] = parsed.port
    return args


@pytest.fixture(scope="module")
def migrated_url() -> Iterator[str]:
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    assert url.startswith("postgresql+asyncpg://") and "sauri_qa" in url
    db_name = f"sauri_qa_turns_{uuid.uuid4().hex}"
    admin_args = _asyncpg_args(url)

    async def admin(sql: str) -> None:
        connection = await asyncpg.connect(**admin_args)
        try:
            await connection.execute(sql)
        finally:
            await connection.close()

    asyncio.run(admin(f'CREATE DATABASE "{db_name}"'))
    target = make_url(url).set(database=db_name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = target
    try:
        command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
        yield target
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


@pytest.fixture
async def factory(migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Factory]:
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(migrated_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(factory: Factory) -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _headers(user_id: str = OWNER) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Synthetic", True)
    return {"Authorization": f"Bearer {token}"}


async def _seed_meeting(factory: Factory) -> tuple[str, str]:
    """Create a meeting with a transcript and one legacy segment."""
    now = datetime.now(UTC)
    meeting_id, transcript_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(Meeting(id=meeting_id, origin="link", process_state="completed",
                            created_by=OWNER, created_at=now))
        await session.flush()
        session.add(Transcript(id=transcript_id, meeting_id=meeting_id, language="es",
                               provider="synthetic", supports_turns=True, created_at=now))
        await session.flush()
        session.add(SpeechTurn(id=str(uuid.uuid4()), transcript_id=transcript_id,
                               text="Hola a todos. Bien, gracias.", start_ms=0, end_ms=9000,
                               sequence=0))
    return meeting_id, transcript_id


async def _add_diarization(
    factory: Factory, meeting_id: str, transcript_id: str, revision: int, state: str
) -> tuple[str, dict[str, str]]:
    """Add a diarization revision with two speakers; returns its id and speaker ids by raw label."""
    now = datetime.now(UTC)
    diarization_id = str(uuid.uuid4())
    speakers = {"SPEAKER_00": str(uuid.uuid4()), "SPEAKER_01": str(uuid.uuid4())}
    async with factory() as session, session.begin():
        session.add(Diarization(id=diarization_id, meeting_id=meeting_id, transcript_id=transcript_id,
                                provider="synthetic", speaker_count=2, processing_revision=revision,
                                diarization_state=state, created_at=now, updated_at=now))
        await session.flush()
        for sequence, (raw_label, speaker_id) in enumerate(speakers.items(), start=1):
            session.add(Speaker(id=speaker_id, diarization_id=diarization_id, raw_label=raw_label,
                                label=f"Speaker {sequence}", sequence=sequence))
    return diarization_id, speakers


# (text, start_ms, end_ms, raw_label or None, state)
WORDS = [
    (" Hola", 0, 400, "SPEAKER_00", "assigned"),
    (" a", 400, 500, "SPEAKER_00", "assigned"),
    (" todos.", 500, 900, None, "unassigned"),
    (" Bien,", 1000, 1300, "SPEAKER_01", "assigned"),
    (" gracias.", 1300, 1800, None, "ambiguous"),
    (" Seguimos", 5000, 5600, "SPEAKER_01", "assigned"),  # > 2000 ms gap, same speaker
    (" luego.", 5600, 6000, "SPEAKER_01", "assigned"),
]


async def _add_words(
    factory: Factory, transcript_id: str, diarization_id: str, speakers: dict[str, str]
) -> None:
    async with factory() as session, session.begin():
        word_ids = []
        for sequence, (text, start_ms, end_ms, _, _) in enumerate(WORDS):
            word_id = str(uuid.uuid4())
            word_ids.append(word_id)
            session.add(TranscriptWord(id=word_id, transcript_id=transcript_id, sequence=sequence,
                                       text=text, start_ms=start_ms, end_ms=end_ms))
        await session.flush()
        for word_id, (_, _, _, raw_label, state) in zip(word_ids, WORDS, strict=True):
            session.add(WordSpeakerAssignment(
                diarization_id=diarization_id, word_id=word_id,
                speaker_id=speakers[raw_label] if raw_label else None, state=state,
                candidates_json=[{"raw_label": "SPEAKER_00", "fraction": 0.5},
                                 {"raw_label": "SPEAKER_01", "fraction": 0.45}]
                if state == "ambiguous" else None,
            ))


async def test_words_become_turns_split_on_speaker_change_and_long_gap(
    client: AsyncClient, factory: Factory
) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    old_id, old_speakers = await _add_diarization(factory, meeting_id, transcript_id, 1, "completed")
    await _add_words(factory, transcript_id, old_id, old_speakers)
    latest_id, speakers = await _add_diarization(factory, meeting_id, transcript_id, 2, "completed")
    async with factory() as session, session.begin():
        words = (await session.scalars(select(TranscriptWord).order_by(TranscriptWord.sequence))).all()
        for word, (_, _, _, raw_label, state) in zip(words, WORDS, strict=True):
            session.add(WordSpeakerAssignment(diarization_id=latest_id, word_id=word.id,
                                              speaker_id=speakers[raw_label] if raw_label else None,
                                              state=state))

    response = await client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["presentation"] == "words"
    assert body["segments"][0]["text"] == "Hola a todos. Bien, gracias."
    turns = body["turns"]
    assert [(t["sequence"], t["speaker_label"], t["text"]) for t in turns] == [
        (1, "Speaker 1", "Hola a todos."),
        (2, "Speaker 2", "Bien, gracias."),
        (3, "Speaker 2", "Seguimos luego."),
    ]
    assert [t["speaker_id"] for t in turns] == [
        speakers["SPEAKER_00"], speakers["SPEAKER_01"], speakers["SPEAKER_01"],
    ]
    assert [(t["start_ms"], t["end_ms"], t["word_count"], t["has_ambiguous"]) for t in turns] == [
        (0, 900, 3, False), (1000, 1800, 2, True), (5000, 6000, 2, False),
    ]
    reconstructed = " ".join(t["text"] for t in turns)
    assert reconstructed == "".join(text for text, *_ in WORDS).strip()


async def test_turn_without_assigned_word_has_null_speaker(client: AsyncClient, factory: Factory) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    diarization_id, speakers = await _add_diarization(factory, meeting_id, transcript_id, 1, "completed")
    async with factory() as session, session.begin():
        word_id = str(uuid.uuid4())
        session.add(TranscriptWord(id=word_id, transcript_id=transcript_id, sequence=0,
                                   text=" Mmm", start_ms=0, end_ms=300))
        await session.flush()
        session.add(WordSpeakerAssignment(diarization_id=diarization_id, word_id=word_id,
                                          speaker_id=None, state="unassigned"))

    body = (await client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=_headers())).json()

    assert body["presentation"] == "words"
    assert body["turns"] == [{
        "sequence": 1, "speaker_id": None, "speaker_label": None, "start_ms": 0, "end_ms": 300,
        "text": "Mmm", "word_count": 1, "has_ambiguous": False,
    }]


async def test_without_words_keeps_segments_unchanged(client: AsyncClient, factory: Factory) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    await _add_diarization(factory, meeting_id, transcript_id, 1, "completed")

    body = (await client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=_headers())).json()

    assert body["presentation"] == "segments"
    assert "turns" not in body
    assert set(body) == {"transcript_id", "meeting_id", "language", "provider", "supports_turns",
                         "created_at", "segments", "presentation"}
    assert [s["text"] for s in body["segments"]] == ["Hola a todos. Bien, gracias."]


async def test_words_without_completed_revision_keep_segments(
    client: AsyncClient, factory: Factory
) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    diarization_id, speakers = await _add_diarization(factory, meeting_id, transcript_id, 1, "in_progress")
    await _add_words(factory, transcript_id, diarization_id, speakers)

    body = (await client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=_headers())).json()

    assert body["presentation"] == "segments"
    assert "turns" not in body


async def test_diarization_returns_latest_completed_revision(client: AsyncClient, factory: Factory) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    await _add_diarization(factory, meeting_id, transcript_id, 1, "completed")
    latest_id, speakers = await _add_diarization(factory, meeting_id, transcript_id, 2, "completed")
    await _add_diarization(factory, meeting_id, transcript_id, 3, "in_progress")
    async with factory() as session, session.begin():
        turn_id = await session.scalar(select(SpeechTurn.id).where(SpeechTurn.transcript_id == transcript_id))
        assert turn_id is not None
        session.add(SpeakerAssignment(id=str(uuid.uuid4()), diarization_id=latest_id, turn_id=turn_id,
                                      speaker_id=speakers["SPEAKER_01"]))

    response = await client.get(f"/api/v1/meetings/{meeting_id}/diarization", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["diarization_id"] == latest_id
    assert body["diarization_state"] == "completed"
    assert [s["label"] for s in body["speakers"]] == ["Speaker 1", "Speaker 2"]
    assert body["assignments"] == [{"turn_id": turn_id, "speaker_id": speakers["SPEAKER_01"]}]


@pytest.mark.parametrize("endpoint", ["transcript", "diarization"])
async def test_another_users_meeting_is_denied_and_audited(
    client: AsyncClient, factory: Factory, endpoint: str
) -> None:
    meeting_id, transcript_id = await _seed_meeting(factory)
    diarization_id, speakers = await _add_diarization(factory, meeting_id, transcript_id, 1, "completed")
    await _add_words(factory, transcript_id, diarization_id, speakers)
    intruder = f"intruder-{uuid.uuid4().hex[:12]}"

    response = await client.get(f"/api/v1/meetings/{meeting_id}/{endpoint}", headers=_headers(intruder))

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
    assert "Hola" not in response.text
    async with factory() as session:
        records = (await session.scalars(select(AccessLog).where(AccessLog.user_id == intruder))).all()
    assert [(r.result, r.resource) for r in records] == [
        ("denied", f"GET /api/v1/meetings/{meeting_id}/{endpoint}")
    ]
