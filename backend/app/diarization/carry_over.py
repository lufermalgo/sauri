"""Carry speaker names over to a newly detected speaker-review revision (#1053).

A re-run assigns fresh speaker identities, and the engine's labels are not stable
between runs. Two speakers are the same person only when they cover (almost) the same
stretches of the same transcript, so the rule is deliberately strict:

* a new speaker inherits the decision of an old speaker only when each is the other's
  best match, and the shared speaking time is at least ``MATCH_THRESHOLD`` of both
  speakers' total speaking time;
* anything else is left undecided, so the review shows as pending and the person
  confirms it. The previous revision and its review are never modified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Diarization,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
)
from app.meetings.speaker_review_state import review_status

MATCH_THRESHOLD = 0.7


def match_speakers(
    overlap_ms: Mapping[tuple[str, str], int],
    new_totals: Mapping[str, int],
    old_totals: Mapping[str, int],
) -> dict[str, str]:
    """Map new speaker id -> old speaker id for the unambiguous pairs only."""
    best_old: dict[str, tuple[str, int]] = {}
    best_new: dict[str, tuple[str, int]] = {}
    for (new_id, old_id), shared in overlap_ms.items():
        if shared > best_old.get(new_id, ("", 0))[1]:
            best_old[new_id] = (old_id, shared)
        if shared > best_new.get(old_id, ("", 0))[1]:
            best_new[old_id] = (new_id, shared)
    mapping: dict[str, str] = {}
    for new_id, (old_id, shared) in best_old.items():
        if best_new[old_id][0] != new_id:
            continue
        if shared >= MATCH_THRESHOLD * new_totals[new_id] and shared >= MATCH_THRESHOLD * old_totals[old_id]:
            mapping[new_id] = old_id
    return mapping


async def carry_over_review(session: AsyncSession, meeting_id: str, revision: int) -> dict[str, Any]:
    """Copy decided names onto the new revision's review; return a content-free report."""
    previous = await session.scalar(
        select(Diarization).where(
            Diarization.meeting_id == meeting_id,
            Diarization.diarization_state == "completed",
            Diarization.processing_revision < revision,
        ).order_by(Diarization.processing_revision.desc()).limit(1)
    )
    current = await session.scalar(
        select(Diarization).where(Diarization.meeting_id == meeting_id, Diarization.processing_revision == revision)
    )
    new_review = await session.scalar(
        select(SpeakerReview).where(
            SpeakerReview.meeting_id == meeting_id, SpeakerReview.processing_revision == revision
        )
    )
    if previous is None or current is None or new_review is None:
        return {}
    old_review = await session.scalar(
        select(SpeakerReview).where(
            SpeakerReview.meeting_id == meeting_id,
            SpeakerReview.processing_revision == previous.processing_revision,
        )
    )
    new_items = {
        item.speaker_key: item
        for item in await session.scalars(select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == new_review.id))
    }
    old_items = {
        item.speaker_key: item
        for item in (
            await session.scalars(select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == old_review.id))
            if old_review is not None else []
        )
    }

    new_side = SpeakerAssignment.__table__.alias("new_side")
    old_side = SpeakerAssignment.__table__.alias("old_side")
    rows = (await session.execute(
        select(SpeechTurn.start_ms, SpeechTurn.end_ms, new_side.c.speaker_id, old_side.c.speaker_id)
        .select_from(new_side)
        .join(old_side, old_side.c.turn_id == new_side.c.turn_id)
        .join(SpeechTurn, SpeechTurn.id == new_side.c.turn_id)
        .where(new_side.c.diarization_id == current.id, old_side.c.diarization_id == previous.id)
    )).all()
    overlap: dict[tuple[str, str], int] = {}
    new_totals: dict[str, int] = {}
    old_totals: dict[str, int] = {}
    for start_ms, end_ms, new_id, old_id in rows:
        span = max(end_ms - start_ms, 0)
        overlap[(new_id, old_id)] = overlap.get((new_id, old_id), 0) + span
        new_totals[new_id] = new_totals.get(new_id, 0) + span
        old_totals[old_id] = old_totals.get(old_id, 0) + span

    carried = 0
    for new_id, old_id in match_speakers(overlap, new_totals, old_totals).items():
        old, item = old_items.get(old_id), new_items.get(new_id)
        if old is None or item is None or old.disposition is None:
            continue
        item.disposition = old.disposition
        # Keep the name the person saw, even when the new run numbers its speakers differently.
        item.chosen_label = old.chosen_label or old.current_label
        item.attribution_state = old.attribution_state
        carried += 1
    new_review.status = review_status({key: item.disposition for key, item in new_items.items()})
    await session.flush()
    return {
        "revision": revision,
        "previous_revision": previous.processing_revision,
        "carried_over": carried,
        "needs_review": new_review.status != "complete",
        "unmatched_speakers": sorted(key for key, item in new_items.items() if item.disposition is None),
    }
