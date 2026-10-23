"""RED contract tests for durable cleanup of uncommitted staged media."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from importlib import import_module
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra import models
from app.ingestion import router as ingestion_router
from app.retention import worker

drain_pending_object_deletions = import_module(
    "app.retention.cleanup"
).drain_pending_object_deletions
Meeting = models.Meeting
PendingObjectDeletion = models.PendingObjectDeletion
RecordingMediaSource = models.RecordingMediaSource
SessionRecording = models.SessionRecording
start_retention_worker = worker.start_retention_worker


class _RecordingObjectStore:
    """Synthetic object store that records deletes and can fail selected refs."""

    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.deleted: list[str] = []

    async def delete(self, reference: str) -> None:
        self.deleted.append(reference)
        if reference in self.failures:
            raise OSError("synthetic object-store failure")


async def _add_pending(
    session: AsyncSession, scope_hash: str, reference: str
) -> PendingObjectDeletion:
    task = PendingObjectDeletion(
        id=str(uuid.uuid4()),
        cleanup_scope_hash=scope_hash,
        object_ref=reference,
    )
    session.add(task)
    await session.commit()
    return task


async def _pending_refs(session: AsyncSession) -> set[str]:
    result = await session.execute(select(PendingObjectDeletion.object_ref))
    return set(result.scalars().all())


@pytest.mark.asyncio
async def test_pending_deletion_model_has_unique_scope_ref_and_no_recording_foreign_key() -> None:
    table = PendingObjectDeletion.__table__

    unique_pairs = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("cleanup_scope_hash", "object_ref") in unique_pairs
    assert not table.foreign_keys


@pytest.mark.asyncio
async def test_cleanup_persists_each_unique_ref_before_attempting_delete(
    session_factory,
) -> None:
    scope_hash = "a" * 64
    observed_before_delete: list[set[str]] = []

    async def observe_persisted_tasks(reference: str) -> None:
        async with session_factory() as observer:
            observed_before_delete.append(await _pending_refs(observer))

    class ObservingStore(_RecordingObjectStore):
        async def delete(self, reference: str) -> None:
            await observe_persisted_tasks(reference)
            await super().delete(reference)

    store = ObservingStore()
    async with session_factory() as setup_session:
        await _add_pending(setup_session, scope_hash, "staged/synthetic-audio")

    async with session_factory() as session:
        await drain_pending_object_deletions(session, store, scope_hash)

    assert observed_before_delete == [{"staged/synthetic-audio"}]
    assert store.deleted == ["staged/synthetic-audio"]


@pytest.mark.asyncio
async def test_successful_delete_is_idempotent_and_removes_only_completed_task(
    db_session: AsyncSession,
) -> None:
    reference = "staged/synthetic-audio"
    await _add_pending(db_session, "a" * 64, reference)
    store = _RecordingObjectStore()

    await drain_pending_object_deletions(db_session, store, "a" * 64)
    await drain_pending_object_deletions(db_session, store, "a" * 64)

    assert store.deleted == [reference]
    assert await _pending_refs(db_session) == set()


@pytest.mark.asyncio
async def test_partial_failure_keeps_only_failed_refs_for_retry(
    db_session: AsyncSession,
    session_factory,
) -> None:
    scope_hash = "b" * 64
    successful = "staged/synthetic-audio"
    failed = "staged/synthetic-video"
    await _add_pending(db_session, scope_hash, successful)
    await _add_pending(db_session, scope_hash, failed)
    store = _RecordingObjectStore({failed})

    await drain_pending_object_deletions(db_session, store, scope_hash)

    assert store.deleted == [successful, failed]
    async with session_factory() as observer:
        assert await _pending_refs(observer) == {failed}


@pytest.mark.asyncio
async def test_live_recording_reference_is_never_deleted(
    db_session: AsyncSession,
    meeting_recording: Meeting,
) -> None:
    scope_hash = "c" * 64
    live_ref = "recordings/committed/synthetic-audio"
    live_source_ref = "recordings/committed/synthetic-video-source"
    await _add_pending(db_session, scope_hash, live_ref)
    await _add_pending(db_session, scope_hash, live_source_ref)
    now = datetime.now(UTC)
    db_session.add(meeting_recording)
    recording = SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_recording.id,
        idempotency_key="synthetic-key",
        capture_origin="web_upload",
        audio_ref=live_ref,
        video_ref=None,
        duration_seconds=1,
        interrupted=False,
        expires_at=None,
        finished_at=now,
    )
    db_session.add(recording)
    db_session.add(
        RecordingMediaSource(
            id=str(uuid.uuid4()),
            recording_id=recording.id,
            kind="video",
            object_ref=live_source_ref,
            quality_label="Original",
        )
    )
    await db_session.commit()
    store = _RecordingObjectStore()

    await drain_pending_object_deletions(db_session, store, scope_hash)

    assert store.deleted == []
    assert await _pending_refs(db_session) == set()


@pytest.mark.asyncio
async def test_retry_is_limited_to_exact_cleanup_scope(db_session: AsyncSession) -> None:
    await _add_pending(db_session, "d" * 64, "staged/scope-one")
    await _add_pending(db_session, "e" * 64, "staged/scope-two")
    store = _RecordingObjectStore()

    await drain_pending_object_deletions(db_session, store, "d" * 64)

    assert store.deleted == ["staged/scope-one"]
    assert await _pending_refs(db_session) == {"staged/scope-two"}


@pytest.mark.asyncio
async def test_scheduled_retention_cycle_recovers_pending_deletions(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    calls: list[object] = []

    async def drain(session, object_store, cleanup_scope_hash=None) -> None:
        calls.append((session, object_store, cleanup_scope_hash))

    async def stop_after_first_cycle(_seconds: float) -> None:
        raise RuntimeError("synthetic stop after scheduled cycle")

    monkeypatch.setattr("app.retention.worker.drain_pending_object_deletions", drain)
    monkeypatch.setattr("app.retention.worker.asyncio.sleep", stop_after_first_cycle)
    store = _RecordingObjectStore()

    with pytest.raises(RuntimeError, match="synthetic stop"):
        await start_retention_worker(session_factory, store, interval_seconds=1)

    assert len(calls) == 1
    assert calls[0][1] is store  # type: ignore[index]
    assert calls[0][2] is None  # type: ignore[index]


@pytest.mark.asyncio
async def test_precommit_failure_persists_ref_before_object_delete(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    reference = "staged/precommit-synthetic-audio"
    observed_tasks: list[list[PendingObjectDeletion]] = []

    class UploadStore(_RecordingObjectStore):
        async def save(self, key: str, content: bytes, content_type: str) -> str:
            return reference

        async def delete(self, object_ref: str) -> None:
            async with session_factory() as observer:
                result = await observer.execute(select(PendingObjectDeletion))
                observed_tasks.append(list(result.scalars().all()))
            await super().delete(object_ref)

    store = UploadStore()
    monkeypatch.setattr(ingestion_router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(ingestion_router, "_get_queue", Mock())
    monkeypatch.setattr(ingestion_router, "create_engine", Mock(return_value=SimpleNamespace(dispose=AsyncMock())))
    monkeypatch.setattr(ingestion_router, "create_session_factory", Mock(return_value=session_factory))

    async def fail_before_recording_commit(**_kwargs) -> None:
        raise RuntimeError("synthetic pre-commit database failure")

    monkeypatch.setattr(ingestion_router, "process_ingestion", fail_before_recording_commit)
    audio = UploadFile(filename="synthetic.webm", file=BytesIO(b"synthetic-audio"))
    video = UploadFile(filename="synthetic-video.webm", file=BytesIO(b"synthetic-video"))
    payload = {
        "meeting_id": "synthetic-meeting-precommit",
        "idempotency_key": "synthetic-precommit-key",
        "capture_origin": "chrome_extension",
        "duration_seconds": 1,
        "video_presence": "separate",
        "video_offset_ms": 0,
    }

    with pytest.raises(RuntimeError, match="synthetic pre-commit"):
        await ingestion_router.upload_recording(
            audio=audio,
            video=video,
            data=json.dumps(payload),
            user=SimpleNamespace(id="synthetic-owner"),
        )

    assert store.deleted == [reference]
    assert len(observed_tasks) == 1
    assert len(observed_tasks[0]) == 1
    assert observed_tasks[0][0].object_ref == reference
    assert len(observed_tasks[0][0].cleanup_scope_hash) == 64
    assert observed_tasks[0][0].cleanup_scope_hash != payload["idempotency_key"]


@pytest.mark.asyncio
async def test_postcommit_queue_failure_never_queues_committed_recording_refs(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    audio_ref = "recordings/committed/synthetic-audio"
    store = _RecordingObjectStore()

    async def save(_key: str, _content: bytes, _content_type: str) -> str:
        return audio_ref

    store.save = save  # type: ignore[attr-defined]
    queue = SimpleNamespace(
        connect=AsyncMock(),
        publish=AsyncMock(side_effect=RuntimeError("synthetic queue unavailable")),
        disconnect=AsyncMock(),
    )
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(ingestion_router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(ingestion_router, "_get_queue", Mock(return_value=queue))
    monkeypatch.setattr(ingestion_router, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(ingestion_router, "create_session_factory", Mock(return_value=session_factory))
    monkeypatch.setattr(
        ingestion_router,
        "record_transition",
        AsyncMock(return_value=SimpleNamespace(successful=True)),
    )
    audio = UploadFile(filename="synthetic.webm", file=BytesIO(b"synthetic-audio"))
    payload = {
        "meeting_id": "synthetic-meeting-postcommit",
        "idempotency_key": "synthetic-postcommit-key",
        "capture_origin": "chrome_extension",
        "duration_seconds": 1,
        "video_presence": "muxed",
    }

    with pytest.raises(RuntimeError, match="synthetic queue unavailable"):
        await ingestion_router.upload_recording(
            audio=audio,
            video=None,
            data=json.dumps(payload),
            user=SimpleNamespace(id="synthetic-owner"),
        )

    async with session_factory() as session:
        recordings = await session.execute(select(SessionRecording))
        committed = recordings.scalars().all()
        pending = await session.execute(select(PendingObjectDeletion.object_ref))

    assert [recording.audio_ref for recording in committed] == [audio_ref]
    assert audio_ref not in set(pending.scalars().all())
    assert store.deleted == []
