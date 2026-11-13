"""RED contracts for revision migration, route and stale-access behavior.

Feature: recording-speaker-review, T-8 RED
Validates: approved tasks.md T-8 and design.md revision-state boundary.
All identifiers and rows in this module are synthetic. No production code is
changed by this task.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem
from app.meetings.speaker_review_service import SpeakerReviewService

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
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def legacy_engine(
    postgres_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncEngine:
    """Real historical schema, not a hand-written approximation of pre-T-17 tables."""
    async with postgres_engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", postgres_engine.url.render_as_string(hide_password=False))
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    await asyncio.to_thread(command.upgrade, config, "013_manual_recovery_persistence")
    return postgres_engine


def _load_migration(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_migration() -> Any:
    """Find the migration that introduces exact processing revisions."""
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = _load_migration(path)
        source = inspect.getsource(module)
        if "processing_revision_id" in source or "processing_state" in source:
            return module
    pytest.fail("no migration introduces processing revisions and processing state")


async def _run_migration(engine: AsyncEngine, migration: Any, direction: str) -> None:
    async with engine.begin() as connection:

        def run(sync_connection: Connection) -> None:
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                getattr(migration, direction)()

        await connection.run_sync(run)


async def _seed_legacy_stage_rows(engine: AsyncEngine) -> None:
    """Create complete and partial legacy records without customer data."""
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        for meeting_id in ("meeting-complete", "meeting-partial"):
            await connection.execute(
                text(
                    "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
                    "VALUES (:id, 'manual', 'completed', :owner, :now)"
                ),
                {"id": meeting_id, "owner": OWNER_ID, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO session_recordings "
                    "(id, meeting_id, idempotency_key, capture_origin, audio_ref, "
                    "duration_seconds, interrupted, finished_at) "
                    "VALUES (:id, :id, :id, 'web_upload', 'synthetic://audio', 10, false, :now)"
                ),
                {"id": meeting_id, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO transcripts "
                    "(id, meeting_id, language, provider, supports_turns, created_at) "
                    "VALUES (:id, :meeting, 'es-CO', 'synthetic', false, :now)"
                ),
                {"id": f"transcript-{meeting_id}", "meeting": meeting_id, "now": now},
            )
        await connection.execute(
            text(
                "INSERT INTO diarizations "
                "(id, meeting_id, transcript_id, provider, speaker_count, "
                "diarization_state, processing_revision, is_legacy, created_at, updated_at) "
                "VALUES ('diarization-complete', 'meeting-complete', "
                "'transcript-meeting-complete', 'synthetic', 1, 'completed', 1, true, :now, :now)"
            ),
            {"now": now},
        )


@pytest.mark.asyncio
async def test_revision_migration_backfills_complete_and_partial_legacy_rows(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    assert migration.down_revision == "013_manual_recovery_persistence"
    await _seed_legacy_stage_rows(postgres_engine)

    await _run_migration(postgres_engine, migration, "upgrade")

    async with postgres_engine.connect() as connection:
        transcript_revisions = (
            await connection.execute(
                text(
                    "SELECT t.meeting_id, r.revision FROM transcripts t "
                    "JOIN processing_revisions r ON r.id = t.processing_revision_id "
                    "AND r.recording_id = t.meeting_id ORDER BY t.meeting_id"
                )
            )
        ).all()
        diarization_revisions = (
            await connection.execute(
                text(
                    "SELECT d.meeting_id, r.revision FROM diarizations d "
                    "JOIN processing_revisions r ON r.id = d.processing_revision_id "
                    "AND r.recording_id = d.meeting_id ORDER BY d.meeting_id"
                )
            )
        ).all()
    assert [tuple(row) for row in transcript_revisions] == [
        ("meeting-complete", LEGACY_REVISION),
        ("meeting-partial", LEGACY_REVISION),
    ]
    assert [tuple(row) for row in diarization_revisions] == [("meeting-complete", LEGACY_REVISION)]
    for meeting_id in ("meeting-complete", "meeting-partial"):
        state = await _state(postgres_engine, meeting_id)
        assert state.active_processing_revision_id is None
        assert state.in_flight_revision_id is None
        assert [row.revision for row in await _revisions(postgres_engine, meeting_id)] == [1]


@pytest.mark.asyncio
async def test_revision_migration_replaces_meeting_only_uniqueness(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    migration = _revision_migration()
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, migration, "upgrade")

    async with postgres_engine.begin() as connection:
        for table, row_id in (
            ("transcripts", "transcript-meeting-complete"),
            ("diarizations", "diarization-complete"),
        ):

            def unique_constraints(sync: Connection, name: str = table) -> Any:
                return sa_inspect(sync).get_unique_constraints(name)

            constraints = await connection.run_sync(unique_constraints)
            keys = [set(item["column_names"]) for item in constraints]
            assert {"meeting_id", "processing_revision_id"} in keys
            assert {"meeting_id"} not in keys
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    if table == "transcripts":
                        await connection.execute(
                            text(
                                "INSERT INTO transcripts (id, meeting_id, language, provider, "
                                "supports_turns, created_at, processing_revision_id) "
                                "SELECT 'transcript-duplicate', meeting_id, language, provider, "
                                "supports_turns, created_at, processing_revision_id "
                                "FROM transcripts WHERE id=:id"
                            ),
                            {"id": row_id},
                        )
                    else:
                        await connection.execute(
                            text(
                                "INSERT INTO diarizations (id, meeting_id, transcript_id, provider, "
                                "speaker_count, diarization_state, processing_revision, is_legacy, "
                                "created_at, updated_at, processing_revision_id) "
                                "SELECT 'diarization-duplicate', meeting_id, transcript_id, provider, "
                                "speaker_count, diarization_state, processing_revision, is_legacy, "
                                "created_at, updated_at, processing_revision_id "
                                "FROM diarizations WHERE id=:id"
                            ),
                            {"id": row_id},
                        )


@pytest.mark.asyncio
async def test_processing_state_schema_has_distinct_active_and_in_flight_pointers(
    postgres_engine: AsyncEngine,
) -> None:
    def inspect_schema(sync_connection: Connection) -> set[str]:
        inspector = sa_inspect(sync_connection)
        names = set(inspector.get_table_names())
        state_table = next(
            (name for name in names if name in {"recording_processing_states", "processing_states"}),
            None,
        )
        assert state_table is not None, "per-recording processing state table is required"
        return {column["name"] for column in inspector.get_columns(state_table)}

    async with postgres_engine.connect() as connection:
        columns = await connection.run_sync(inspect_schema)
    assert "active_processing_revision_id" in columns
    assert "in_flight_revision_id" in columns


def test_revision_qualified_review_routes_are_registered() -> None:
    """The revision path is explicit for writes and excerpt reads."""
    from app.main import app

    routes = {route.path: route.methods for route in app.routes if isinstance(route, APIRoute)}
    review_path = "/api/v1/meetings/{meeting_id}/speaker-review"
    disposition_path = "/api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}"
    excerpt_path = f"{disposition_path}/excerpt"

    assert routes.get(review_path) == {"GET"}
    assert routes.get(disposition_path) == {"PUT"}
    assert routes.get(excerpt_path) == {"GET"}

    # State-changing/read operations must name their revision; an unqualified
    # route could mutate or return whichever revision happened to be current.
    assert "/api/v1/meetings/{meeting_id}/speaker-review/speakers/{speaker_id}" not in routes
    assert "/api/v1/meetings/{meeting_id}/speaker-review/speakers/{speaker_id}/excerpt" not in routes


@pytest.fixture
async def api_db_url(postgres_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> str:
    url = postgres_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    return url


@pytest.fixture
async def api_client(api_db_url: str) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


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
async def test_stale_revision_excerpt_is_rejected(api_client: AsyncClient, api_db_url: str) -> None:
    meeting_id, _, _ = await _persist_synthetic_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review/revisions/2/speakers/speaker-synthetic-1/excerpt",
        headers=_auth_headers(),
    )

    assert response.status_code == 409


# T-17's service is deliberately absent in RED. Assert its contract at the
# call site, so collection and import errors never masquerade as RED evidence.
def _admission_service() -> Any:
    try:
        module = importlib.import_module("app.meetings.processing_revision_service")
    except ModuleNotFoundError as error:
        if error.name != "app.meetings.processing_revision_service":
            raise
        pytest.fail("T-17 contract absent: ProcessingRevisionService.admit_candidate", pytrace=False)
    service = getattr(module, "ProcessingRevisionService", None)
    assert service is not None and callable(getattr(service, "admit_candidate", None))
    return service


async def _meeting(engine: AsyncEngine, owner: str = OWNER_ID) -> str:
    meeting_id = str(uuid.uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO meetings (id, origin, process_state, created_by, created_at) "
                "VALUES (:id, 'manual', 'completed', :owner, :now)"
            ),
            {"id": meeting_id, "owner": owner, "now": datetime.now(UTC)},
        )
        await connection.execute(
            text(
                "INSERT INTO session_recordings "
                "(id, meeting_id, idempotency_key, capture_origin, audio_ref, "
                "duration_seconds, interrupted, finished_at) "
                "VALUES (:id, :id, :id, 'web_upload', 'synthetic://audio', 10, false, :now)"
            ),
            {"id": meeting_id, "now": datetime.now(UTC)},
        )
    return meeting_id


async def _state(engine: AsyncEngine, meeting_id: str) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT active_processing_revision_id, in_flight_revision_id, "
                    "legacy_compatibility_revision_id "
                    "FROM recording_processing_states WHERE recording_id=:id"
                ),
                {"id": meeting_id},
            )
        ).one()


async def _revisions(engine: AsyncEngine, meeting_id: str) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                text("SELECT id, revision FROM processing_revisions WHERE recording_id=:id ORDER BY revision"),
                {"id": meeting_id},
            )
        ).all()


@pytest.mark.asyncio
async def test_admission_is_caller_transaction_and_exact_retry_preserves_revision(
    postgres_engine: AsyncEngine,
) -> None:
    service = _admission_service()
    meeting_id = await _meeting(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID, recording_id=meeting_id, request_id="request-1", request_fingerprint="sha256:audio-a"
        )
        assert len(await _revisions_in_session(session, meeting_id)) == 1
        # Caller owns the commit. An independent transaction cannot see the row yet.
        assert await _revisions(postgres_engine, meeting_id) == []
        await service(session).admit_candidate(
            owner_id=OWNER_ID, recording_id=meeting_id, request_id="request-1", request_fingerprint="sha256:audio-a"
        )
        assert len(await _revisions_in_session(session, meeting_id)) == 1
    revisions = await _revisions(postgres_engine, meeting_id)
    assert len(revisions) == 1
    state = await _state(postgres_engine, meeting_id)
    assert state.active_processing_revision_id is None
    assert state.in_flight_revision_id == revisions[0].id
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID, recording_id=meeting_id, request_id="request-1", request_fingerprint="sha256:audio-a"
        )
    assert await _revisions(postgres_engine, meeting_id) == revisions


async def _revisions_in_session(session: AsyncSession, meeting_id: str) -> Any:
    return (
        await session.execute(
            text("SELECT id, revision FROM processing_revisions WHERE recording_id=:id"),
            {"id": meeting_id},
        )
    ).all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_id,fingerprint",
    [
        ("request-1", "sha256:changed"),
        ("request-2", "sha256:different"),
    ],
)
async def test_changed_fingerprint_or_distinct_request_cannot_displace_inflight(
    postgres_engine: AsyncEngine,
    request_id: str,
    fingerprint: str,
) -> None:
    service = _admission_service()
    meeting_id = await _meeting(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID, recording_id=meeting_id, request_id="request-1", request_fingerprint="sha256:audio-a"
        )
    state_before = await _state(postgres_engine, meeting_id)
    revisions_before = await _revisions(postgres_engine, meeting_id)
    async with factory() as session, session.begin():
        try:
            outcome = await service(session).admit_candidate(
                owner_id=OWNER_ID,
                recording_id=meeting_id,
                request_id=request_id,
                request_fingerprint=fingerprint,
            )
        except ValueError:
            outcome = None
        assert outcome is None or getattr(outcome, "outcome", None) == "conflict"
    assert await _state(postgres_engine, meeting_id) == state_before
    assert await _revisions(postgres_engine, meeting_id) == revisions_before


@pytest.mark.asyncio
async def test_two_concurrent_distinct_admissions_allocate_one_candidate(
    postgres_engine: AsyncEngine,
) -> None:
    service = _admission_service()
    meeting_id = await _meeting(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    locked = asyncio.Event()
    release = asyncio.Event()

    async def first() -> None:
        async with factory() as session, session.begin():
            await service(session).admit_candidate(
                owner_id=OWNER_ID, recording_id=meeting_id, request_id="request-a", request_fingerprint="sha256:a"
            )
            locked.set()
            await asyncio.wait_for(release.wait(), 5)

    async def second() -> Any:
        await asyncio.wait_for(locked.wait(), 5)
        async with factory() as session, session.begin():
            try:
                return await service(session).admit_candidate(
                    owner_id=OWNER_ID,
                    recording_id=meeting_id,
                    request_id="request-b",
                    request_fingerprint="sha256:b",
                )
            except ValueError:
                return None

    first_task = asyncio.create_task(first())
    await asyncio.wait_for(locked.wait(), 5)
    second_task = asyncio.create_task(second())
    try:
        await asyncio.sleep(0.1)
        assert not second_task.done(), "distinct admission bypassed the state-row lock"
    finally:
        release.set()
        await first_task
    outcome = await asyncio.wait_for(second_task, 5)
    assert outcome is None or getattr(outcome, "outcome", None) == "conflict"
    revisions = await _revisions(postgres_engine, meeting_id)
    assert len(revisions) == 1
    state = await _state(postgres_engine, meeting_id)
    assert state.active_processing_revision_id is None
    assert state.in_flight_revision_id == revisions[0].id


@pytest.mark.asyncio
async def test_foreign_owner_cannot_admit_or_mutate_processing_state(
    postgres_engine: AsyncEngine,
) -> None:
    service = _admission_service()
    meeting_id = await _meeting(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        try:
            outcome = await service(session).admit_candidate(
                owner_id="another-owner",
                recording_id=meeting_id,
                request_id="request-foreign",
                request_fingerprint="sha256:foreign",
            )
        except ValueError:
            outcome = None
        assert outcome is None or getattr(outcome, "outcome", None) == "not_found"
    assert await _revisions(postgres_engine, meeting_id) == []


@pytest.mark.asyncio
async def test_partial_legacy_get_before_and_after_admission_keeps_compatibility_only(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
    api_client: AsyncClient,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    meeting_id = "meeting-partial"
    path = f"/api/v1/meetings/{meeting_id}"
    transcript = await api_client.get(f"{path}/transcript", headers=_auth_headers())
    diarization = await api_client.get(f"{path}/diarization", headers=_auth_headers())
    review = await api_client.get(f"{path}/speaker-review", headers=_auth_headers())
    assert transcript.status_code == 200
    assert transcript.json()["transcript_id"] == "transcript-meeting-partial"
    assert diarization.status_code == 404
    assert review.status_code == 409
    assert (await _state(postgres_engine, meeting_id)).active_processing_revision_id is None

    service = _admission_service()
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID, recording_id=meeting_id, request_id="partial-new", request_fingerprint="sha256:new"
        )
    state = await _state(postgres_engine, meeting_id)
    assert state.active_processing_revision_id is None
    assert state.in_flight_revision_id != state.legacy_compatibility_revision_id
    review = await api_client.get(f"{path}/speaker-review", headers=_auth_headers())
    assert review.status_code == 409
    assert (await _state(postgres_engine, meeting_id)) == state
    transcript = await api_client.get(f"{path}/transcript", headers=_auth_headers())
    diarization = await api_client.get(f"{path}/diarization", headers=_auth_headers())
    assert transcript.status_code == 200
    assert transcript.json()["transcript_id"] == "transcript-meeting-partial"
    assert diarization.status_code == 404


@pytest.mark.asyncio
async def test_complete_legacy_get_while_candidate_inflight_cannot_activate_compatibility(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
    api_client: AsyncClient,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    service = _admission_service()
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID,
            recording_id="meeting-complete",
            request_id="candidate-new",
            request_fingerprint="sha256:new",
        )
    before = await _state(postgres_engine, "meeting-complete")
    assert before.active_processing_revision_id is None
    assert before.in_flight_revision_id is not None
    # Candidate stage rows may exist but compatibility reads stay pinned to 1.
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, "
                "created_at, processing_revision_id) "
                "SELECT 'transcript-candidate', meeting_id, language, provider, supports_turns, "
                "created_at, :candidate FROM transcripts WHERE id='transcript-meeting-complete'"
            ),
            {"candidate": before.in_flight_revision_id},
        )
        await connection.execute(
            text(
                "INSERT INTO diarizations (id, meeting_id, transcript_id, provider, speaker_count, "
                "diarization_state, processing_revision, is_legacy, created_at, updated_at, "
                "processing_revision_id) "
                "SELECT 'diarization-candidate', meeting_id, 'transcript-candidate', provider, "
                "speaker_count, diarization_state, 2, false, created_at, updated_at, :candidate "
                "FROM diarizations WHERE id='diarization-complete'"
            ),
            {"candidate": before.in_flight_revision_id},
        )
    response = await api_client.get(
        "/api/v1/meetings/meeting-complete/speaker-review",
        headers=_auth_headers(),
    )
    assert response.status_code == 409
    assert await _state(postgres_engine, "meeting-complete") == before
    transcript = await api_client.get(
        "/api/v1/meetings/meeting-complete/transcript",
        headers=_auth_headers(),
    )
    diarization = await api_client.get(
        "/api/v1/meetings/meeting-complete/diarization",
        headers=_auth_headers(),
    )
    assert transcript.status_code == diarization.status_code == 200
    assert transcript.json()["transcript_id"] == "transcript-meeting-complete"
    assert diarization.json()["diarization_id"] == "diarization-complete"


@pytest.mark.asyncio
async def test_active_review_is_pinned_not_latest_and_owner_isolated(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    # A persisted review at revision 2 is not necessarily active; only the
    # processing-state pointer may select a user-visible review.
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    service = _admission_service()
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await service(session).admit_candidate(
            owner_id=OWNER_ID,
            recording_id="meeting-complete",
            request_id="candidate-new",
            request_fingerprint="sha256:new",
        )
    rows = await _revisions(postgres_engine, "meeting-complete")
    assert [row.revision for row in rows] == [1, 2]
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE recording_processing_states SET active_processing_revision_id=:active "
                "WHERE recording_id='meeting-complete'"
            ),
            {"active": rows[0].id},
        )
        for ordinal in (1, 2):
            await connection.execute(
                text(
                    "INSERT INTO speaker_reviews (id, meeting_id, processing_revision, status, created_at) "
                    "VALUES (:id, 'meeting-complete', :revision, 'pending', :now)"
                ),
                {"id": f"synthetic-review-{ordinal}", "revision": ordinal, "now": datetime.now(UTC)},
            )
    async with factory() as session, session.begin():
        active = await SpeakerReviewService(session).get_active_review(OWNER_ID, "meeting-complete")
        foreign = await SpeakerReviewService(session).get_active_review("another-owner", "meeting-complete")
    assert active is not None
    assert active["review_id"] == "synthetic-review-1"
    assert active["revision_id"] == 1
    assert foreign is None


@pytest.mark.asyncio
async def test_pending_active_review_rejects_new_candidate_without_displacing_review(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    legacy_id = (await _revisions(postgres_engine, "meeting-complete"))[0].id
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE recording_processing_states SET active_processing_revision_id=:revision "
                "WHERE recording_id='meeting-complete'"
            ),
            {"revision": legacy_id},
        )
        await connection.execute(
            text(
                "INSERT INTO speaker_reviews (id, meeting_id, processing_revision, status, created_at) "
                "VALUES ('pending-review', 'meeting-complete', 1, 'pending', :now)"
            ),
            {"now": datetime.now(UTC)},
        )
        await connection.execute(
            text(
                "INSERT INTO speaker_review_items (id, review_id, speaker_key, current_label, "
                "attribution_state, version) VALUES "
                "('pending-item', 'pending-review', 'speaker-1', 'Speaker 1', 'uncertain', 1)"
            )
        )
    state_before = await _state(postgres_engine, "meeting-complete")
    service = _admission_service()
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        try:
            outcome = await service(session).admit_candidate(
                owner_id=OWNER_ID,
                recording_id="meeting-complete",
                request_id="request-after-review",
                request_fingerprint="sha256:new",
            )
        except ValueError:
            outcome = None
        assert outcome is None or getattr(outcome, "outcome", None) == "conflict"
    assert await _state(postgres_engine, "meeting-complete") == state_before
    assert len(await _revisions(postgres_engine, "meeting-complete")) == 1
    async with factory() as session, session.begin():
        active = await SpeakerReviewService(session).get_active_review(OWNER_ID, "meeting-complete")
    assert active is not None
    assert active["review_id"] == "pending-review"
    assert active["remaining_speaker_ids"] == ["speaker-1"]


def _pipeline(engine: AsyncEngine) -> tuple[Any, AsyncMock]:
    """Exercise the design's finalizer with persisted stages and synthetic collaborators."""
    try:
        module = importlib.import_module("app.transcription.processing_pipeline")
    except ModuleNotFoundError as error:
        if error.name != "app.transcription.processing_pipeline":
            raise
        pytest.fail("T-15 contract absent: ProcessingPipeline.finalize/get_review", pytrace=False)
    pipeline_type = getattr(module, "ProcessingPipeline", None)
    assert pipeline_type is not None
    matcher = AsyncMock()
    matcher.match = AsyncMock(return_value={"state": "uncertain"})
    validator = AsyncMock(return_value={"speaker-synthetic-1": "synthetic://validated-speaker-1-0-1000"})
    pipeline = pipeline_type(
        async_sessionmaker(engine, expire_on_commit=False),
        transcription_provider=AsyncMock(return_value={"text": "synthetic speech"}),
        diarization_provider=AsyncMock(return_value={"speakers": ["speaker-synthetic-1"]}),
        speaker_identity_matcher=matcher,
        excerpt_validator=validator,
    )
    return pipeline, validator


async def _complete_candidate_stages(pipeline: Any, revision_id: str) -> None:
    """Set up durable completed outputs through the approved processing boundary."""
    assert await pipeline.process_stage(revision_id, "transcription") is not None
    assert await pipeline.process_stage(revision_id, "diarization") is not None


@pytest.mark.asyncio
async def test_exact_current_candidate_finalization_activates_and_clears_atomically(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    legacy_id = (await _revisions(postgres_engine, "meeting-complete"))[0].id
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await _admission_service()(session).admit_candidate(
            owner_id=OWNER_ID,
            recording_id="meeting-complete",
            request_id="ready-candidate",
            request_fingerprint="sha256:ready",
        )
    candidate_id = (await _state(postgres_engine, "meeting-complete")).in_flight_revision_id
    assert candidate_id is not None and candidate_id != legacy_id
    pipeline, validator = _pipeline(postgres_engine)
    assert await pipeline.finalize(candidate_id) is None  # stages have not completed
    assert (await _state(postgres_engine, "meeting-complete")).in_flight_revision_id == candidate_id
    await _complete_candidate_stages(pipeline, candidate_id)
    async with postgres_engine.connect() as connection:
        stages = (
            await connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM transcripts WHERE processing_revision_id=:revision), "
                    "(SELECT count(*) FROM diarizations WHERE processing_revision_id=:revision)"
                ),
                {"revision": candidate_id},
            )
        ).one()
    assert tuple(stages) == (1, 1)  # completed stages are real persisted rows
    assert (await _state(postgres_engine, "meeting-complete")).active_processing_revision_id is None

    review = await pipeline.finalize(candidate_id)
    state = await _state(postgres_engine, "meeting-complete")
    assert review is not None
    assert review["processing_revision_id"] == candidate_id
    assert review["excerpts"] == {"speaker-synthetic-1": "synthetic://validated-speaker-1-0-1000"}
    validator.assert_awaited_once()
    assert state.active_processing_revision_id == candidate_id
    assert state.in_flight_revision_id is None
    assert await pipeline.get_review("meeting-complete") == review
    assert await pipeline.finalize(candidate_id) == review  # no second aggregate
    async with postgres_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT r.id, i.excerpt_ref FROM speaker_reviews r "
                    "JOIN speaker_review_items i ON i.review_id=r.id "
                    "WHERE r.meeting_id='meeting-complete' AND r.processing_revision=2"
                )
            )
        ).all()
    assert len(rows) == 1 and rows[0].excerpt_ref == "synthetic://validated-speaker-1-0-1000"


@pytest.mark.asyncio
async def test_non_current_candidate_cannot_activate_or_clear_current_inflight(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await _admission_service()(session).admit_candidate(
            owner_id=OWNER_ID,
            recording_id="meeting-complete",
            request_id="current-candidate",
            request_fingerprint="sha256:current",
        )
    current = (await _state(postgres_engine, "meeting-complete")).in_flight_revision_id
    legacy = (await _revisions(postgres_engine, "meeting-complete"))[0].id
    assert current is not None and current != legacy
    pipeline, validator = _pipeline(postgres_engine)
    await _complete_candidate_stages(pipeline, current)
    before = await _state(postgres_engine, "meeting-complete")
    assert await pipeline.finalize(legacy) is None
    validator.assert_not_awaited()
    assert await _state(postgres_engine, "meeting-complete") == before
    async with postgres_engine.connect() as connection:
        count = (
            await connection.execute(text("SELECT count(*) FROM speaker_reviews WHERE meeting_id='meeting-complete'"))
        ).scalar_one()
    assert count == 0
    assert await pipeline.finalize(current) is not None
    activated = await _state(postgres_engine, "meeting-complete")
    assert activated.active_processing_revision_id == current
    assert activated.in_flight_revision_id is None
    assert await pipeline.finalize(legacy) is None
    assert await _state(postgres_engine, "meeting-complete") == activated


@pytest.mark.asyncio
async def test_get_first_holds_shared_state_lock_and_pending_review_blocks_admission(
    legacy_engine: AsyncEngine,
    postgres_engine: AsyncEngine,
) -> None:
    await _seed_legacy_stage_rows(postgres_engine)
    await _run_migration(postgres_engine, _revision_migration(), "upgrade")
    legacy_id = (await _revisions(postgres_engine, "meeting-complete"))[0].id
    assert (await _state(postgres_engine, "meeting-complete")).active_processing_revision_id is None
    # A real legacy speaker interval, inside the synthetic 10-second recording,
    # supplies the excerpt validator with same-speaker, in-bounds speech.
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO speech_turns (id, transcript_id, text, start_ms, end_ms, sequence) "
                "VALUES ('legacy-turn', 'transcript-meeting-complete', 'synthetic speech', 0, 1000, 1)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO speakers (id, diarization_id, raw_label, label, sequence) "
                "VALUES ('speaker-synthetic-1', 'diarization-complete', 'SPEAKER_00', 'Speaker 1', 1)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO speaker_assignments (id, diarization_id, turn_id, speaker_id, overlap_ms) "
                "VALUES ('legacy-assignment', 'diarization-complete', 'legacy-turn', "
                "'speaker-synthetic-1', 1000)"
            )
        )
    pipeline, validator = _pipeline(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    started = asyncio.Event()
    release = asyncio.Event()
    attempted = asyncio.Event()
    service = _admission_service()

    async def read_first() -> None:
        # This call must create the review and switch the active pointer under
        # the same state lock used by admission, not just read a pre-seeded review.
        review = await pipeline.get_review("meeting-complete")
        assert review is not None and review["processing_revision_id"] == legacy_id
        assert review["excerpts"] == {"speaker-synthetic-1": "synthetic://validated-speaker-1-0-1000"}
        validator.assert_awaited_once()
        state = await _state(postgres_engine, "meeting-complete")
        assert state.active_processing_revision_id == legacy_id
        assert state.in_flight_revision_id is None
        async with factory() as session, session.begin():
            result = await SpeakerReviewService(session).get_active_review(OWNER_ID, "meeting-complete")
            assert result is not None and result["review_id"] == review["review_id"]
            started.set()
            await asyncio.wait_for(release.wait(), 5)

    async def admit_second() -> Any:
        await asyncio.wait_for(started.wait(), 5)
        async with factory() as session, session.begin():
            attempted.set()
            try:
                return await service(session).admit_candidate(
                    owner_id=OWNER_ID,
                    recording_id="meeting-complete",
                    request_id="new-request",
                    request_fingerprint="sha256:new",
                )
            except ValueError:
                return None

    reader = asyncio.create_task(read_first())
    await asyncio.wait_for(started.wait(), 5)
    admission = asyncio.create_task(admit_second())
    await asyncio.wait_for(attempted.wait(), 5)
    try:
        await asyncio.sleep(0.1)
        assert not admission.done(), "GET did not hold the shared processing-state lock"
    finally:
        release.set()
        await reader
    outcome = await asyncio.wait_for(admission, 5)
    assert outcome is None or getattr(outcome, "outcome", None) == "conflict"
    assert len(await _revisions(postgres_engine, "meeting-complete")) == 1
    assert (await _state(postgres_engine, "meeting-complete")).active_processing_revision_id == legacy_id
    async with postgres_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT r.status, i.speaker_key, i.excerpt_ref FROM speaker_reviews r "
                    "JOIN speaker_review_items i ON i.review_id=r.id "
                    "WHERE r.meeting_id='meeting-complete' AND r.processing_revision=1"
                )
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("pending", "speaker-synthetic-1", "synthetic://validated-speaker-1-0-1000")
    ]
