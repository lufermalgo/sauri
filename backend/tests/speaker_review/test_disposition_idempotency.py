"""Persistent idempotency behavior for speaker-review disposition writes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


async def _persisted_review(db_session: Any) -> tuple[str, str]:
    """Create a minimal synthetic database-backed review fixture."""
    from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem

    meeting_id = "meeting-db-test"
    review_id = "review-db-test"
    db_session.add(
        Meeting(
            id=meeting_id,
            meet_link="https://meet.google.com/abc-defg-hij",
            origin="link",
            calendar_invite_id=None,
            scheduled_start_time=None,
            process_state="completed",
            failure_cause=None,
            created_by="owner-db-test",
            created_at=datetime.now(UTC),
        )
    )
    db_session.add(
        SpeakerReview(
            id=review_id,
            meeting_id=meeting_id,
            processing_revision=1,
            status="pending",
            created_at=datetime.now(UTC),
        )
    )
    db_session.add(
        SpeakerReviewItem(
            id="item-db-test",
            review_id=review_id,
            speaker_key="speaker-db-test",
            current_label="Speaker 1",
            disposition=None,
            chosen_label=None,
            attribution_state="uncertain",
            version=1,
        )
    )
    db_session.add(
        SpeakerReviewItem(
            id="item-db-test-2",
            review_id=review_id,
            speaker_key="speaker-db-test-2",
            current_label="Speaker 2",
            disposition=None,
            chosen_label=None,
            attribution_state="uncertain",
            version=1,
        )
    )
    await db_session.flush()
    return meeting_id, review_id


async def _write(
    db_session: Any,
    meeting_id: str,
    request: dict[str, Any],
    speaker_id: str = "speaker-db-test",
) -> dict[str, Any]:
    from app.meetings.speaker_review_service import SpeakerReviewService

    return await SpeakerReviewService(db_session).record_disposition(
        "owner-db-test", meeting_id, "1", speaker_id, request, 1
    )


@settings(max_examples=100)
@given(
    request=st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.text(max_size=20),
        min_size=1,
        max_size=8,
    )
)
def test_canonical_hash_ignores_idempotency_key_and_mapping_order(request: dict[str, str]) -> None:
    """Transport key and mapping insertion order do not alter request identity."""
    from app.meetings.disposition_idempotency import canonical_request_hash

    payload = {**request, "idempotency_key": "key-one"}
    reordered = dict(reversed(list(payload.items())))
    same_request_other_key = {**payload, "idempotency_key": "key-two"}
    assert canonical_request_hash(payload) == canonical_request_hash(reordered)
    assert canonical_request_hash(payload) == canonical_request_hash(same_request_other_key)


async def test_persistent_replay_returns_original_result_without_second_mutation(db_session: Any) -> None:
    """A duplicate write replays the persisted result without advancing again."""
    from sqlalchemy import select

    from app.infra.models import SpeakerReviewIdempotencyReceipt, SpeakerReviewItem

    meeting_id, _ = await _persisted_review(db_session)
    request = {
        "disposition": "named",
        "label": "Synthetic person",
        "expected_version": 1,
        "idempotency_key": "key-db-test",
    }
    async with db_session.begin_nested():
        applied = await _write(db_session, meeting_id, request)
    async with db_session.begin_nested():
        replayed = await _write(db_session, meeting_id, request)

    assert applied["outcome"] == "apply"
    assert replayed == {"outcome": "replay", "result": applied["result"]}
    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    receipts = list((await db_session.scalars(select(SpeakerReviewIdempotencyReceipt))).all())
    assert item is not None and item.version == 2 and item.disposition == "named"
    assert len(receipts) == 1


async def test_key_reuse_and_stale_version_conflict_without_mutation(db_session: Any) -> None:
    """Conflicts do not alter a disposition or create another receipt."""
    from sqlalchemy import select

    from app.infra.models import SpeakerReviewIdempotencyReceipt, SpeakerReviewItem

    meeting_id, _ = await _persisted_review(db_session)
    request = {
        "disposition": "confirmed",
        "expected_version": 1,
        "idempotency_key": "key-db-conflict",
    }
    async with db_session.begin_nested():
        applied = await _write(db_session, meeting_id, request)
    async with db_session.begin_nested():
        key_conflict = await _write(
            db_session,
            meeting_id,
            {**request, "disposition": "named", "label": "Changed"},
        )
    async with db_session.begin_nested():
        stale = await _write(
            db_session,
            meeting_id,
            {
                "disposition": "confirmed",
                "expected_version": 1,
                "idempotency_key": "new-key",
            },
        )

    assert applied["outcome"] == "apply"
    assert key_conflict["outcome"] == "conflict_key_hash_mismatch"
    assert stale["outcome"] == "conflict_stale_version"
    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    receipts = list((await db_session.scalars(select(SpeakerReviewIdempotencyReceipt))).all())
    assert item is not None and item.version == 2 and item.disposition == "confirmed"
    assert len(receipts) == 1


async def test_same_key_reused_for_another_item_is_a_conflict(db_session: Any) -> None:
    """A persisted key cannot be redirected to another speaker item."""
    meeting_id, _ = await _persisted_review(db_session)
    request = {
        "disposition": "confirmed",
        "expected_version": 1,
        "idempotency_key": "key-cross-item",
    }
    async with db_session.begin_nested():
        applied = await _write(db_session, meeting_id, request)
    async with db_session.begin_nested():
        replay = await _write(db_session, meeting_id, request, "speaker-db-test-2")

    assert applied["outcome"] == "apply"
    assert replay["outcome"] == "conflict_key_hash_mismatch"


async def test_receipt_schema_is_persistently_available(async_engine: Any) -> None:
    """The database schema exposes durable idempotency receipts."""
    from sqlalchemy import inspect

    async with async_engine.connect() as connection:
        tables = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names())
    assert "speaker_review_idempotency_receipts" in tables


async def test_database_receipt_failure_rolls_back_disposition(db_session: Any) -> None:
    """A real SQLite constraint failure in receipt insertion rolls back the item update."""
    from sqlalchemy import select, text
    from sqlalchemy.exc import IntegrityError

    from app.infra.models import SpeakerReviewItem

    meeting_id, _ = await _persisted_review(db_session)
    await db_session.execute(
        text(
            "CREATE TRIGGER reject_synthetic_receipt BEFORE INSERT "
            "ON speaker_review_idempotency_receipts BEGIN "
            "SELECT RAISE(ABORT, 'synthetic receipt rejection'); END"
        )
    )
    request = {
        "disposition": "confirmed",
        "expected_version": 1,
        "idempotency_key": "key-db-trigger-failure",
    }
    with pytest.raises(IntegrityError, match="synthetic receipt rejection"):
        await _write(db_session, meeting_id, request)

    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    assert item is not None and item.version == 1 and item.disposition is None


async def test_outer_transaction_failure_rolls_back_disposition_and_receipt(db_session: Any) -> None:
    """A failed enclosing transaction leaves neither persistent write behind."""
    from sqlalchemy import select

    from app.infra.models import SpeakerReviewIdempotencyReceipt, SpeakerReviewItem

    meeting_id, _ = await _persisted_review(db_session)
    request = {
        "disposition": "confirmed",
        "expected_version": 1,
        "idempotency_key": "key-db-rollback",
    }
    with pytest.raises(RuntimeError, match="simulated transaction abort"):
        async with db_session.begin_nested():
            result = await _write(db_session, meeting_id, request)
            assert result["outcome"] == "apply"
            raise RuntimeError("simulated transaction abort")

    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    receipt = await db_session.scalar(
        select(SpeakerReviewIdempotencyReceipt).where(
            SpeakerReviewIdempotencyReceipt.idempotency_key == "key-db-rollback"
        )
    )
    assert item is not None and item.version == 1 and item.disposition is None
    assert receipt is None
