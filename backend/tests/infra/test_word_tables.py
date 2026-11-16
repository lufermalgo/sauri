"""transcript_words and word_speaker_assignments against a real PostgreSQL (U3.1, #923).

Each test module run creates its own throwaway database next to the one in
SAURI_QA_POSTGRES_URL (which must be a disposable ``sauri_qa`` database), builds
the schema with ``alembic upgrade head`` and drops the database afterwards.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.infra.database import Base
from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    Transcript,
    TranscriptWord,
    WordSpeakerAssignment,
)
from app.infra.object_store import ObjectStore
from app.retention.worker import run_retention_deletion

BACKEND = Path(__file__).resolve().parents[2]
TABLES = {"transcript_words", "word_speaker_assignments"}


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
    db_name = f"sauri_qa_words_{uuid.uuid4().hex}"
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
async def factory(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _table_names(url: str) -> set[str]:
    connection = await asyncpg.connect(**_asyncpg_args(url))
    try:
        rows = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY($1::text[])",
            list(TABLES),
        )
        return {row["tablename"] for row in rows}
    finally:
        await connection.close()


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, transcript_expired: bool = False
) -> dict[str, str]:
    now = datetime.now(UTC)
    ids = {key: str(uuid.uuid4()) for key in ("meeting", "transcript", "diarization", "speaker")}
    ids |= {"word_a": str(uuid.uuid4()), "word_b": str(uuid.uuid4())}
    async with factory() as session, session.begin():
        session.add(Meeting(id=ids["meeting"], origin="link", process_state="completed",
                            created_by="synthetic-user", created_at=now))
        await session.flush()
        session.add(Transcript(id=ids["transcript"], meeting_id=ids["meeting"], language="es",
                               provider="synthetic", supports_turns=True, created_at=now,
                               expires_at=now - timedelta(seconds=1) if transcript_expired else None))
        await session.flush()
        session.add(Diarization(id=ids["diarization"], meeting_id=ids["meeting"],
                                transcript_id=ids["transcript"], provider="synthetic",
                                speaker_count=1, processing_revision=1,
                                diarization_state="completed", created_at=now, updated_at=now))
        await session.flush()
        session.add(Speaker(id=ids["speaker"], diarization_id=ids["diarization"],
                            raw_label="SPEAKER_00", label="Speaker 1", sequence=1))
        session.add_all([
            TranscriptWord(id=ids["word_a"], transcript_id=ids["transcript"], sequence=0,
                           text=" Hola", start_ms=0, end_ms=400, probability=0.9),
            TranscriptWord(id=ids["word_b"], transcript_id=ids["transcript"], sequence=1,
                           text=" mundo", start_ms=400, end_ms=800, probability=None,
                           timing_repaired=True),
        ])
        await session.flush()
        session.add_all([
            WordSpeakerAssignment(diarization_id=ids["diarization"], word_id=ids["word_a"],
                                  speaker_id=ids["speaker"], state="assigned"),
            WordSpeakerAssignment(diarization_id=ids["diarization"], word_id=ids["word_b"],
                                  speaker_id=None, state="ambiguous",
                                  candidates_json=[{"speaker_id": ids["speaker"], "fraction": 0.5},
                                                   {"speaker_id": None, "fraction": 0.5}]),
        ])
    return ids


async def _counts(factory: async_sessionmaker[AsyncSession], transcript_id: str) -> tuple[int, int]:
    async with factory() as session:
        words = await session.scalar(
            select(func.count()).select_from(TranscriptWord)
            .where(TranscriptWord.transcript_id == transcript_id))
        assignments = await session.scalar(
            select(func.count()).select_from(WordSpeakerAssignment)
            .join(TranscriptWord, TranscriptWord.id == WordSpeakerAssignment.word_id)
            .where(TranscriptWord.transcript_id == transcript_id))
        return int(words or 0), int(assignments or 0)


def test_head_is_single_and_chains_after_summary_failure_cause() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["023_summary_request_timestamps"]
    assert script.get_revision("019_failed_summary_request").down_revision == "018_transcript_language_default"
    assert script.get_revision("017_transcript_words").down_revision == "016_summary_failure_cause"


def test_upgrade_downgrade_upgrade_is_clean(migrated_url: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    assert asyncio.run(_table_names(migrated_url)) == TABLES
    command.downgrade(config, "016_summary_failure_cause")
    assert asyncio.run(_table_names(migrated_url)) == set()
    command.upgrade(config, "head")
    assert asyncio.run(_table_names(migrated_url)) == TABLES


async def test_migration_matches_models(migrated_url: str) -> None:
    engine = create_async_engine(migrated_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            diffs = await connection.run_sync(
                lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata))
    finally:
        await engine.dispose()
    relevant = [diff for diff in diffs if any(table in repr(diff) for table in TABLES)]
    assert relevant == []


async def test_word_sequence_is_unique_per_transcript(factory: async_sessionmaker[AsyncSession]) -> None:
    ids = await _seed(factory)
    with pytest.raises(IntegrityError, match="uq_transcript_word_sequence"):
        async with factory() as session, session.begin():
            session.add(TranscriptWord(id=str(uuid.uuid4()), transcript_id=ids["transcript"],
                                       sequence=0, text=" otra", start_ms=0, end_ms=10))


async def test_assignment_primary_key_is_diarization_and_word(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(factory)
    with pytest.raises(IntegrityError, match="word_speaker_assignments_pkey"):
        async with factory() as session, session.begin():
            session.add(WordSpeakerAssignment(diarization_id=ids["diarization"],
                                              word_id=ids["word_a"], state="unassigned"))


async def test_assignment_state_is_constrained(factory: async_sessionmaker[AsyncSession]) -> None:
    ids = await _seed(factory)
    async with factory() as session, session.begin():
        await session.execute(
            WordSpeakerAssignment.__table__.delete().where(
                WordSpeakerAssignment.word_id == ids["word_a"]))
    with pytest.raises(IntegrityError, match="ck_word_speaker_assignments_state_valid"):
        async with factory() as session, session.begin():
            session.add(WordSpeakerAssignment(diarization_id=ids["diarization"],
                                              word_id=ids["word_a"], state="maybe"))


async def test_deleting_transcript_cascades_words_and_assignments(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(factory)
    assert await _counts(factory, ids["transcript"]) == (2, 2)
    async with factory() as session, session.begin():
        # Diarizations reference transcripts without cascade; drop them as retention does.
        await session.execute(Diarization.__table__.delete().where(
            Diarization.transcript_id == ids["transcript"]))
        await session.execute(Transcript.__table__.delete().where(Transcript.id == ids["transcript"]))
    assert await _counts(factory, ids["transcript"]) == (0, 0)
    async with factory() as session:
        remaining = await session.scalar(select(func.count()).select_from(WordSpeakerAssignment)
                                          .where(WordSpeakerAssignment.word_id.in_(
                                              [ids["word_a"], ids["word_b"]])))
    assert remaining == 0


async def test_deleting_diarization_cascades_only_assignments(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(factory)
    async with factory() as session, session.begin():
        await session.execute(Diarization.__table__.delete().where(
            Diarization.id == ids["diarization"]))
    assert await _counts(factory, ids["transcript"]) == (2, 0)


async def test_retention_expiry_removes_words_and_assignments(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    expired = await _seed(factory, transcript_expired=True)
    kept = await _seed(factory)
    async with factory() as session:
        await run_retention_deletion(session, AsyncMock(spec=ObjectStore), datetime.now(UTC))
    assert await _counts(factory, expired["transcript"]) == (0, 0)
    assert await _counts(factory, kept["transcript"]) == (2, 2)
    async with factory() as session:
        assert await session.get(Transcript, expired["transcript"]) is None
        assert await session.get(Diarization, expired["diarization"]) is None
        assert await session.get(Transcript, kept["transcript"]) is not None
