"""Persistent speaker-review disposition write service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Diarization,
    Meeting,
    SpeakerReview,
    SpeakerReviewIdempotencyReceipt,
    SpeakerReviewItem,
)
from app.meetings.disposition_idempotency import canonical_request_hash
from app.meetings.speaker_review_state import VALID_DISPOSITIONS, is_complete, review_status


class SpeakerReviewService:
    """Read persisted review state and apply atomic speaker dispositions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_review(
        self, owner_id: str, meeting_id: str, revision_id: int | None = None
    ) -> dict[str, Any] | None:
        """Return a historical review, or the last completed generation's review."""
        meeting = await self._session.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.created_by == owner_id)
        )
        if meeting is None:
            return None

        if revision_id is None:
            revision_id = await self._session.scalar(
                select(Diarization.processing_revision)
                .where(Diarization.meeting_id == meeting_id, Diarization.diarization_state == "completed")
                .order_by(Diarization.processing_revision.desc())
                .limit(1)
            )
            if revision_id is None:
                # Existing review-only records predate persisted diarization generations.
                has_generation = await self._session.scalar(
                    select(Diarization.id).where(Diarization.meeting_id == meeting_id).limit(1)
                )
                if has_generation is not None:
                    return None

        statement = select(SpeakerReview).where(SpeakerReview.meeting_id == meeting_id)
        if revision_id is not None:
            statement = statement.where(SpeakerReview.processing_revision == revision_id)
        review = await self._session.scalar(statement.order_by(SpeakerReview.processing_revision.desc()).limit(1))
        if review is None:
            return None
        return await self._snapshot(review)

    async def _snapshot(self, review: SpeakerReview) -> dict[str, Any]:
        """Resolve labels from every item while presenting only pending ones."""
        items = list(
            (
                await self._session.scalars(
                    select(SpeakerReviewItem)
                    .where(SpeakerReviewItem.review_id == review.id)
                    .order_by(SpeakerReviewItem.speaker_key)
                )
            ).all()
        )
        outstanding = [item for item in items if item.disposition is None]
        return {
            "review_id": review.id,
            "revision_id": review.processing_revision,
            "status": review_status({item.speaker_key: item.disposition for item in items}),
            "remaining_speaker_ids": [item.speaker_key for item in outstanding],
            "labels_by_speaker_id": {item.speaker_key: item.chosen_label or item.current_label for item in items},
            "items": [
                {
                    "speaker_id": item.speaker_key,
                    "current_label": item.current_label,
                    "attribution_state": item.attribution_state,
                    "disposition": item.disposition,
                    "excerpt_ref": item.excerpt_ref,
                    "expected_version": item.version,
                }
                for item in outstanding
            ],
        }

    async def record_disposition(
        self,
        owner_id: str,
        meeting_id: str,
        revision_id: str,
        speaker_id: str,
        request: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        """Persist a disposition and idempotency receipt in one savepoint.

        The enclosing request transaction owns the final commit. A savepoint
        keeps the item and receipt atomic even when this method is composed
        with other database work.
        """
        async with self._session.begin_nested():
            meeting = await self._session.scalar(
                select(Meeting).where(Meeting.id == meeting_id, Meeting.created_by == owner_id)
            )
            if meeting is None:
                return {"outcome": "not_found", "result": None}

            review = await self._session.scalar(
                select(SpeakerReview)
                .where(
                    SpeakerReview.meeting_id == meeting_id,
                    SpeakerReview.processing_revision == int(revision_id),
                )
                .with_for_update()
            )
            if review is None:
                return {"outcome": "not_found", "result": None}

            item = await self._session.scalar(
                select(SpeakerReviewItem)
                .where(SpeakerReviewItem.review_id == review.id, SpeakerReviewItem.speaker_key == speaker_id)
                .with_for_update()
            )
            if item is None:
                return {"outcome": "not_found", "result": None}

            key = request.get("idempotency_key")
            if not isinstance(key, str) or not key:
                return {"outcome": "invalid_request", "result": None}
            request_hash = canonical_request_hash(request)
            receipt = await self._session.scalar(
                select(SpeakerReviewIdempotencyReceipt).where(
                    SpeakerReviewIdempotencyReceipt.review_id == review.id,
                    SpeakerReviewIdempotencyReceipt.idempotency_key == key,
                )
            )
            if receipt is not None:
                if receipt.item_id != item.id or receipt.request_hash != request_hash:
                    return {"outcome": "conflict_key_hash_mismatch", "result": None}
                return {"outcome": "replay", "result": receipt.response}

            disposition = request.get("disposition")
            if disposition not in VALID_DISPOSITIONS:
                return {"outcome": "invalid_request", "result": None}
            if item.version != expected_version or request.get("expected_version") != expected_version:
                return {"outcome": "conflict_stale_version", "result": None}
            if item.disposition is not None:
                return {"outcome": "conflict_stale_version", "result": None}

            label = request.get("label")
            normalized_label: str | None = None
            if disposition in {"named", "corrected"}:
                if not isinstance(label, str) or not label.strip():
                    return {"outcome": "invalid_request", "result": None}
                normalized_label = label.strip()

            item.disposition = disposition
            if normalized_label is not None:
                item.chosen_label = normalized_label
            item.version += 1
            items = list(
                (
                    await self._session.scalars(
                        select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == review.id)
                    )
                ).all()
            )
            statuses = {row.speaker_key: row.disposition for row in items}
            review.status = "complete" if is_complete(statuses) else "pending"
            result = await self._snapshot(review)
            self._session.add(
                SpeakerReviewIdempotencyReceipt(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    item_id=item.id,
                    idempotency_key=key,
                    request_hash=request_hash,
                    response=result,
                )
            )
            await self._session.flush()
            return {"outcome": "apply", "result": result}
