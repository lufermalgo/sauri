"""Durable cleanup of staged objects that were not committed to a recording."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    PendingObjectDeletion,
    RecordingMediaSource,
    SessionRecording,
)
from app.infra.object_store import ObjectStore

logger = logging.getLogger(__name__)


async def persist_pending_object_deletions(
    session: AsyncSession,
    cleanup_scope_hash: str,
    object_refs: list[str | None],
) -> None:
    """Commit unique object refs as durable tasks before attempting deletion."""
    unique_refs = dict.fromkeys(ref for ref in object_refs if ref)
    for object_ref in unique_refs:
        existing = await session.scalar(
            select(PendingObjectDeletion.id).where(
                PendingObjectDeletion.cleanup_scope_hash == cleanup_scope_hash,
                PendingObjectDeletion.object_ref == object_ref,
            )
        )
        if existing is None:
            session.add(
                PendingObjectDeletion(
                    id=str(uuid.uuid4()),
                    cleanup_scope_hash=cleanup_scope_hash,
                    object_ref=object_ref,
                )
            )
    await session.commit()


async def _is_live_reference(session: AsyncSession, object_ref: str) -> bool:
    recording_id = await session.scalar(
        select(SessionRecording.id)
        .where(
            or_(
                SessionRecording.audio_ref == object_ref,
                SessionRecording.video_ref == object_ref,
            )
        )
        .limit(1)
    )
    if recording_id is not None:
        return True

    media_source_id = await session.scalar(
        select(RecordingMediaSource.id)
        .where(RecordingMediaSource.object_ref == object_ref)
        .limit(1)
    )
    return media_source_id is not None


async def drain_pending_object_deletions(
    session: AsyncSession,
    object_store: ObjectStore,
    cleanup_scope_hash: str | None = None,
) -> None:
    """Delete unreferenced staged refs and retain failed tasks for retry.

    Passing a scope hash limits draining to one idempotent upload attempt. The
    scheduled retention worker omits it to recover all outstanding tasks.
    """
    statement = select(PendingObjectDeletion)
    if cleanup_scope_hash is not None:
        statement = statement.where(
            PendingObjectDeletion.cleanup_scope_hash == cleanup_scope_hash
        )

    result = await session.execute(statement)
    pending_tasks = list(result.scalars().all())
    completed_tasks: list[PendingObjectDeletion] = []
    for task in pending_tasks:
        if await _is_live_reference(session, task.object_ref):
            completed_tasks.append(task)
            continue

        try:
            await object_store.delete(task.object_ref)
        except Exception:
            logger.exception(
                "Could not delete staged object for cleanup scope %s",
                task.cleanup_scope_hash,
            )
            continue

        completed_tasks.append(task)

    # Keep all tasks durable until every delete attempt has been made. If the
    # process stops mid-cycle, completed deletes are safe to retry idempotently.
    for task in completed_tasks:
        await session.delete(task)
    if completed_tasks:
        await session.commit()
