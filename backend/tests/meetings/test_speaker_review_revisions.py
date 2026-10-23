"""RED contracts for revision migration, route and stale-access behavior.

Feature: recording-speaker-review, T-8 RED
Validates: approved tasks.md T-8 and design.md revision-state boundary.
All identifiers and rows in this module are synthetic. No production code is
changed by this task.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "alembic" / "versions"
LEGACY_REVISION = 1
OWNER_ID = "t8-synthetic-owner"


@pytest.fixture
async def postgres_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Use only the explicitly isolated, high-port T-8 PostgreSQL database."""
    database_url = os.environ.get("SAURI_T8_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SAURI_T8_TEST_DATABASE_URL to the isolated T-8 PostgreSQL database")
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.port is None
        or url.port < 55000
        or not (url.database or "").startswith("sauri_t8")
    ):
        pytest.fail("T-8 migration tests require a local high-port database named sauri_t8*")

    engine = create_async_engine(database_url, echo=False)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    try:
        yield engine
    finally:
        await engine.dispose()


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_migration():
    """Find the migration that introduces exact processing revisions."""
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = _load_migration(path)
        source = inspect.getsource(module)
        if "processing_revision_id" in source or "processing_state" in source:
            return module
    pytest.fail("no migration introduces processing revisions and processing state")


async def _run_migration(engine: AsyncEngine, migration, direction: str) -> None:
    async with engine.begin() as connection:
        def run(sync_connection) -> None:
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                getattr(migration, direction)()

        await connection.run_sync(run)


async def _seed_legacy_stage_rows(engine: AsyncEngine) -> None:
    """Create complete and partial legacy records without customer data."""
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS diarizations"))
        await connection.execute(text("DROP TABLE IF EXISTS transcripts"))
        await connection.execute(
            text(
                "CREATE TABLE transcripts (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) NOT NULL, "
                "content TEXT NOT NULL, UNIQUE(meeting_id))"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE diarizations (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) NOT NULL, "
                "content TEXT NOT NULL, UNIQUE(meeting_id))"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO transcripts (id, meeting_id, content) VALUES "
                "('transcript-complete', 'meeting-complete', 'synthetic transcript'), "
                "('transcript-partial', 'meeting-partial', 'synthetic partial transcript')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO diarizations (id, meeting_id, content) VALUES "
                "('diarization-complete', 'meeting-complete', 'synthetic diarization')"
            )
        )


@pytest.mark.asyncio
async def test_revision_migration_backfills_complete_and_partial_legacy_rows(
    postgres_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    assert migration.down_revision in {
        "009_recording_media_sources",
        "009_speaker_review_idempotency_receipts",
    }
    await _seed_legacy_stage_rows(postgres_engine)

    await _run_migration(postgres_engine, migration, "upgrade")

    async with postgres_engine.connect() as connection:
        transcript_revisions = (
            await connection.execute(
                text("SELECT meeting_id, processing_revision_id FROM transcripts ORDER BY meeting_id")
            )
        ).all()
        diarization_revisions = (
            await connection.execute(
                text("SELECT meeting_id, processing_revision_id FROM diarizations ORDER BY meeting_id")
            )
        ).all()
    assert transcript_revisions == [
        ("meeting-complete", LEGACY_REVISION),
        ("meeting-partial", LEGACY_REVISION),
    ]
    assert diarization_revisions == [("meeting-complete", LEGACY_REVISION)]


@pytest.mark.asyncio
async def test_revision_migration_replaces_meeting_only_uniqueness(
    postgres_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, migration, "upgrade")

    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO transcripts (id, meeting_id, content, processing_revision_id) "
                "VALUES ('transcript-revision-2', 'meeting-complete', 'new synthetic transcript', 2)"
            )
        )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO transcripts (id, meeting_id, content, processing_revision_id) "
                        "VALUES ('transcript-duplicate-revision', 'meeting-complete', 'duplicate', 2)"
                    )
                )
        await connection.execute(
            text(
                "INSERT INTO diarizations (id, meeting_id, content, processing_revision_id) "
                "VALUES ('diarization-revision-2', 'meeting-complete', 'new synthetic diarization', 2)"
            )
        )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO diarizations (id, meeting_id, content, processing_revision_id) "
                        "VALUES ('diarization-duplicate-revision', 'meeting-complete', 'duplicate', 2)"
                    )
                )


@pytest.mark.asyncio
async def test_processing_state_schema_has_distinct_active_and_in_flight_pointers(
    async_engine: AsyncEngine,
) -> None:
    def inspect_schema(sync_connection):
        inspector = sa_inspect(sync_connection)
        names = set(inspector.get_table_names())
        state_table = next(
            (name for name in names if name in {"recording_processing_states", "processing_states"}),
            None,
        )
        assert state_table is not None, "per-recording processing state table is required"
        return {column["name"] for column in inspector.get_columns(state_table)}

    async with async_engine.connect() as connection:
        columns = await connection.run_sync(inspect_schema)
    assert "active_processing_revision_id" in columns
    assert "in_flight_revision_id" in columns


def test_revision_qualified_review_routes_are_registered() -> None:
    """The revision path is explicit for writes and excerpt reads."""
    from app.main import app

    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
    review_path = "/api/v1/meetings/{meeting_id}/speaker-review"
    disposition_path = (
        "/api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}"
    )
    excerpt_path = f"{disposition_path}/excerpt"

    assert routes.get(review_path) == {"GET"}
    assert routes.get(disposition_path) == {"PUT"}
    assert routes.get(excerpt_path) == {"GET"}

    # State-changing/read operations must name their revision; an unqualified
    # route could mutate or return whichever revision happened to be current.
    assert "/api/v1/meetings/{meeting_id}/speaker-review/speakers/{speaker_id}" not in routes
    assert "/api/v1/meetings/{meeting_id}/speaker-review/speakers/{speaker_id}/excerpt" not in routes


def _auth_headers() -> dict[str, str]:
    token = create_token(OWNER_ID, "t8-owner@sauri.local", "Synthetic Reviewer", True)
    return {"Authorization": f"Bearer {token}"}


async def _persist_synthetic_review(database_url: str) -> tuple[str, str, str]:
    """Persist one synthetic pending review for stale-revision HTTP requests."""
    meeting_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/synthetic-meeting",
                origin="manual",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=OWNER_ID,
                created_at=now,
            )
        )
        session.add(
            SpeakerReview(
                id=review_id,
                meeting_id=meeting_id,
                processing_revision=1,
                status="pending",
                created_at=now,
            )
        )
        session.add(
            SpeakerReviewItem(
                id=item_id,
                review_id=review_id,
                speaker_key="speaker-synthetic-1",
                current_label="Speaker 1",
                disposition=None,
                chosen_label=None,
                attribution_state="uncertain",
                version=1,
            )
        )
    await engine.dispose()
    return meeting_id, review_id, item_id


@pytest.mark.asyncio
async def test_stale_revision_disposition_is_rejected_without_mutation(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, _, item_id = await _persist_synthetic_review(api_db_url)

    response = await api_client.put(
        f"/api/v1/meetings/{meeting_id}/speaker-review/revisions/2/speakers/speaker-synthetic-1",
        headers=_auth_headers() | {"Idempotency-Key": "t8-stale-write"},
        json={"disposition": "confirmed", "expected_version": 1},
    )

    assert response.status_code == 409
    engine = create_async_engine(api_db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = await session.get(SpeakerReviewItem, item_id)
    await engine.dispose()
    assert item is not None
    assert item.disposition is None
    assert item.version == 1


@pytest.mark.asyncio
async def test_stale_revision_excerpt_is_rejected(
    api_client: AsyncClient, api_db_url: str
) -> None:
    meeting_id, _, _ = await _persist_synthetic_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review/revisions/2/"
        "speakers/speaker-synthetic-1/excerpt",
        headers=_auth_headers(),
    )

    assert response.status_code == 409
