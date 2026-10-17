"""RED tests for idempotent speaker-review disposition writes.

Feature: recording-speaker-review, T-2 RED (Issue #235)
Validates: Requirements 4.1-4.4 through correctness property 9, "safe idempotent
review writes" (approved design ``014d84c6``).

Prospective seams exercised here are the ones the approved design declares; they
are intentionally imported inside each test so the recorded RED failure names the
missing contract instead of failing collection for the whole module:

* ``app.meetings.disposition_idempotency`` — the pure idempotency contract for a
  single review-item write. Expected surface:

  - ``canonical_request_hash(request) -> str``: stable hash of the canonical
    request payload, independent of mapping key order and sensitive to every
    field that distinguishes one write from another.
  - ``execute_disposition_write(aggregate, request, *, fail_at=None) -> dict``:
    resolves and applies one write inside a single all-or-nothing transaction.
    The returned mapping carries ``outcome`` (``apply``, ``replay``,
    ``conflict_key_hash_mismatch`` or ``conflict_stale_version``) and ``result``
    (the saved response payload, or ``None`` for a conflict). ``fail_at`` names
    the transaction step that must fail (``sample``, ``disposition`` or
    ``receipt``) and makes the call raise ``RuntimeError`` after rolling back.

  The aggregate is the plain synthetic mapping these tests build: ``items``
  (``speaker_id -> {"version": int, "disposition": str | None}``), ``samples``
  (appended immutable identity samples) and ``receipts``
  (``idempotency_key -> {"request_hash": str, "result": dict}``).
* ``app.meetings.speaker_review_service.SpeakerReviewService.record_disposition``
  — the service seam whose parameter list the design fixes as
  ``(owner_id, meeting_id, revision_id, speaker_id, request, expected_version)``.

Every owner, speaker, identity, label and embedding reference below is synthetic.
No real meeting audio, transcript or identity data is used.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any, TypeAlias

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

VALID_DISPOSITIONS: tuple[str, ...] = ("named", "corrected", "confirmed")
WRITE_OUTCOMES: frozenset[str] = frozenset(
    {"apply", "replay", "conflict_key_hash_mismatch", "conflict_stale_version"}
)
TRANSACTION_STEPS: tuple[str, ...] = ("sample", "disposition", "receipt")
SAMPLED_DISPOSITIONS: tuple[str, ...] = ("named", "corrected")

Aggregate: TypeAlias = dict[str, Any]
Request: TypeAlias = dict[str, Any]
Write: TypeAlias = dict[str, Any]


# ---------------------------------------------------------------------------
# Synthetic builders
# ---------------------------------------------------------------------------

_HEX = st.text(alphabet="abcdef0123456789", min_size=4, max_size=8)


def synthetic_aggregate(versions: dict[str, int]) -> Aggregate:
    """Build an in-memory review aggregate with one item per speaker."""
    return {
        "items": {
            speaker_id: {"version": version, "disposition": None}
            for speaker_id, version in versions.items()
        },
        "samples": [],
        "receipts": {},
    }


def synthetic_request(
    *,
    speaker_id: str,
    disposition: str,
    expected_version: int,
    idempotency_key: str,
    target_identity_id: str | None = None,
    label: str | None = None,
) -> Request:
    """Build one canonical disposition request payload."""
    return {
        "speaker_id": speaker_id,
        "disposition": disposition,
        "target_identity_id": target_identity_id,
        "label": label,
        "expected_version": expected_version,
        "idempotency_key": idempotency_key,
    }


@st.composite
def aggregates(draw: st.DrawFn) -> Aggregate:
    """Generate a synthetic review with one to six undisposed speaker items."""
    speaker_ids = draw(
        st.lists(_HEX.map("spk-{}".format), min_size=1, max_size=6, unique=True)
    )
    versions = draw(
        st.lists(
            st.integers(min_value=0, max_value=4),
            min_size=len(speaker_ids),
            max_size=len(speaker_ids),
        )
    )
    return synthetic_aggregate(dict(zip(speaker_ids, versions, strict=True)))


@st.composite
def requests_for(draw: st.DrawFn, aggregate: Aggregate) -> Request:
    """Generate a valid request for one item of ``aggregate`` at its version."""
    speaker_id = draw(st.sampled_from(sorted(aggregate["items"])))
    disposition = draw(st.sampled_from(VALID_DISPOSITIONS))
    target_identity_id: str | None = None
    label: str | None = None
    if disposition in SAMPLED_DISPOSITIONS:
        if draw(st.booleans()):
            target_identity_id = "identity-" + draw(_HEX)
        else:
            label = "Label " + draw(_HEX)
    return synthetic_request(
        speaker_id=speaker_id,
        disposition=disposition,
        expected_version=aggregate["items"][speaker_id]["version"],
        idempotency_key="key-" + draw(_HEX),
        target_identity_id=target_identity_id,
        label=label,
    )


def same_key_different_payload(request: Request) -> Request:
    """Reuse the idempotency key with a payload that must hash differently."""
    payload = copy.deepcopy(request)
    if payload["label"] is not None:
        payload["label"] = payload["label"] + "-other"
    elif payload["target_identity_id"] is not None:
        payload["target_identity_id"] = payload["target_identity_id"] + "-other"
    else:
        payload["disposition"] = "named"
        payload["label"] = "Label other"
    return payload


def stale_version_request(request: Request, aggregate: Aggregate, drift: int) -> Request:
    """Build a request under a different key whose version no longer matches."""
    payload = copy.deepcopy(request)
    current = aggregate["items"][request["speaker_id"]]["version"]
    payload["idempotency_key"] = request["idempotency_key"] + "-retry"
    payload["expected_version"] = current + drift if current + drift >= 0 else current + 1
    return payload


def assert_write_contract(write: Write) -> None:
    """Assert the shared shape of every disposition-write outcome."""
    assert write["outcome"] in WRITE_OUTCOMES
    if write["outcome"] in {"apply", "replay"}:
        assert isinstance(write["result"], dict)
    else:
        assert write["result"] is None


# ---------------------------------------------------------------------------
# Deterministic tests — property 9
# ---------------------------------------------------------------------------


def test_replay_same_key_and_hash_returns_saved_result_without_second_sample() -> None:
    """Same key plus same canonical request replays the saved result only."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    aggregate = synthetic_aggregate({"spk-0001": 0, "spk-0002": 0})
    request = synthetic_request(
        speaker_id="spk-0001",
        disposition="named",
        expected_version=0,
        idempotency_key="key-0001",
        target_identity_id="identity-0001",
    )

    first = execute_disposition_write(aggregate, request)
    assert_write_contract(first)
    assert first["outcome"] == "apply"
    assert len(aggregate["samples"]) == 1
    assert aggregate["items"]["spk-0001"]["disposition"] == "named"
    assert aggregate["items"]["spk-0001"]["version"] == 1
    assert aggregate["items"]["spk-0002"] == {"version": 0, "disposition": None}

    frozen_items = copy.deepcopy(aggregate["items"])
    frozen_samples = copy.deepcopy(aggregate["samples"])
    frozen_receipts = copy.deepcopy(aggregate["receipts"])
    assert len(frozen_receipts) == 1

    for _ in range(3):
        replayed = execute_disposition_write(aggregate, copy.deepcopy(request))
        assert_write_contract(replayed)
        assert replayed["outcome"] == "replay"
        assert replayed["result"] == first["result"]
        assert aggregate["items"] == frozen_items
        assert aggregate["samples"] == frozen_samples
        assert aggregate["receipts"] == frozen_receipts


def test_reused_key_with_different_request_hash_conflicts_without_mutation() -> None:
    """Reusing a key for another request is a conflict, never a second write."""
    from app.meetings.disposition_idempotency import (
        canonical_request_hash,
        execute_disposition_write,
    )

    aggregate = synthetic_aggregate({"spk-0001": 3})
    request = synthetic_request(
        speaker_id="spk-0001",
        disposition="corrected",
        expected_version=3,
        idempotency_key="key-0002",
        label="Label ana",
    )
    conflicting = same_key_different_payload(request)
    assert conflicting["idempotency_key"] == request["idempotency_key"]
    assert canonical_request_hash(conflicting) != canonical_request_hash(request)

    first = execute_disposition_write(aggregate, request)
    assert first["outcome"] == "apply"
    frozen = copy.deepcopy(aggregate)

    rejected = execute_disposition_write(aggregate, conflicting)
    assert_write_contract(rejected)
    assert rejected["outcome"] == "conflict_key_hash_mismatch"
    assert aggregate == frozen


def test_different_key_with_stale_expected_version_conflicts_without_mutation() -> None:
    """A competing write under a new key and stale version changes nothing."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    aggregate = synthetic_aggregate({"spk-0001": 2})
    request = synthetic_request(
        speaker_id="spk-0001",
        disposition="confirmed",
        expected_version=2,
        idempotency_key="key-0003",
    )
    stale = stale_version_request(request, aggregate, drift=-1)
    assert stale["idempotency_key"] != request["idempotency_key"]
    assert stale["expected_version"] == 1

    frozen = copy.deepcopy(aggregate)

    rejected = execute_disposition_write(aggregate, stale)
    assert_write_contract(rejected)
    assert rejected["outcome"] == "conflict_stale_version"
    assert aggregate == frozen
    assert aggregate["receipts"] == {}


def test_transaction_failure_rolls_back_disposition_and_identity_sample_together() -> None:
    """A failing step rolls back the disposition and the identity sample."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    for step in TRANSACTION_STEPS:
        aggregate = synthetic_aggregate({"spk-0001": 0})
        request = synthetic_request(
            speaker_id="spk-0001",
            disposition="named",
            expected_version=0,
            idempotency_key="key-0004",
            target_identity_id="identity-0004",
        )
        frozen = copy.deepcopy(aggregate)

        with pytest.raises(RuntimeError):
            execute_disposition_write(aggregate, request, fail_at=step)

        assert aggregate == frozen
        assert aggregate["samples"] == []
        assert aggregate["items"]["spk-0001"] == {"version": 0, "disposition": None}
        assert aggregate["receipts"] == {}


def test_record_disposition_service_signature_matches_approved_contract() -> None:
    """The service seam keeps the design-declared disposition-write signature."""
    from app.meetings.speaker_review_service import SpeakerReviewService

    record_disposition = SpeakerReviewService.record_disposition
    parameters = [
        name for name in inspect.signature(record_disposition).parameters if name != "self"
    ]

    assert inspect.iscoroutinefunction(record_disposition)
    assert parameters[:6] == [
        "owner_id",
        "meeting_id",
        "revision_id",
        "speaker_id",
        "request",
        "expected_version",
    ]


# ---------------------------------------------------------------------------
# Property tests — correctness property 9 (>=100 examples each)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=st.data(), retries=st.integers(min_value=1, max_value=5))
def test_property_9_retry_sequence_replays_saved_result_without_new_writes(
    data: st.DataObject, retries: int
) -> None:
    """Any retry sequence with the same key/hash replays and never mutates again."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    aggregate = data.draw(aggregates())
    request = data.draw(requests_for(aggregate))

    first = execute_disposition_write(aggregate, request)
    assert_write_contract(first)
    assert first["outcome"] == "apply"
    expected_samples = 0 if request["disposition"] == "confirmed" else 1
    assert len(aggregate["samples"]) == expected_samples
    assert aggregate["items"][request["speaker_id"]]["disposition"] == request["disposition"]
    assert len(aggregate["receipts"]) == 1

    frozen_items = copy.deepcopy(aggregate["items"])
    frozen_samples = copy.deepcopy(aggregate["samples"])
    frozen_receipts = copy.deepcopy(aggregate["receipts"])

    for _ in range(retries):
        replayed = execute_disposition_write(aggregate, copy.deepcopy(request))
        assert_write_contract(replayed)
        assert replayed["outcome"] == "replay"
        assert replayed["result"] == first["result"]
        assert aggregate["items"] == frozen_items
        assert aggregate["samples"] == frozen_samples
        assert aggregate["receipts"] == frozen_receipts


@settings(max_examples=100)
@given(data=st.data())
def test_property_9_any_key_reuse_with_different_hash_conflicts(data: st.DataObject) -> None:
    """Every reused key carrying another request hash conflicts without mutation."""
    from app.meetings.disposition_idempotency import (
        canonical_request_hash,
        execute_disposition_write,
    )

    aggregate = data.draw(aggregates())
    request = data.draw(requests_for(aggregate))
    conflicting = same_key_different_payload(request)
    assert conflicting["idempotency_key"] == request["idempotency_key"]
    assert canonical_request_hash(conflicting) != canonical_request_hash(request)

    first = execute_disposition_write(aggregate, request)
    assert first["outcome"] == "apply"
    frozen = copy.deepcopy(aggregate)

    rejected = execute_disposition_write(aggregate, conflicting)
    assert_write_contract(rejected)
    assert rejected["outcome"] == "conflict_key_hash_mismatch"
    assert aggregate == frozen


@settings(max_examples=100)
@given(data=st.data(), drift=st.integers(min_value=1, max_value=5), newer=st.booleans())
def test_property_9_any_stale_expected_version_conflicts_without_mutation(
    data: st.DataObject, drift: int, newer: bool
) -> None:
    """Any mismatched expected version under a new key conflicts and mutates nothing."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    aggregate = data.draw(aggregates())
    request = data.draw(requests_for(aggregate))
    current = aggregate["items"][request["speaker_id"]]["version"]
    stale = stale_version_request(request, aggregate, drift if newer else -drift)
    assert stale["expected_version"] != current

    frozen = copy.deepcopy(aggregate)

    rejected = execute_disposition_write(aggregate, stale)
    assert_write_contract(rejected)
    assert rejected["outcome"] == "conflict_stale_version"
    assert aggregate == frozen


@settings(max_examples=100)
@given(data=st.data(), step=st.sampled_from(TRANSACTION_STEPS))
def test_property_9_any_transaction_failure_rolls_back_every_write(
    data: st.DataObject, step: str
) -> None:
    """Failure at any step leaves disposition, samples and receipts unchanged."""
    from app.meetings.disposition_idempotency import execute_disposition_write

    aggregate = data.draw(aggregates())
    request = data.draw(requests_for(aggregate))
    frozen = copy.deepcopy(aggregate)

    with pytest.raises(RuntimeError):
        execute_disposition_write(aggregate, request, fail_at=step)

    assert aggregate == frozen


@settings(max_examples=100)
@given(data=st.data())
def test_property_9_canonical_request_hash_is_stable_and_payload_sensitive(
    data: st.DataObject,
) -> None:
    """The canonical hash ignores key order and distinguishes any changed field."""
    from app.meetings.disposition_idempotency import canonical_request_hash

    aggregate = data.draw(aggregates())
    request = data.draw(requests_for(aggregate))

    assert canonical_request_hash(copy.deepcopy(request)) == canonical_request_hash(request)
    reordered = {name: request[name] for name in reversed(list(request))}
    assert canonical_request_hash(reordered) == canonical_request_hash(request)

    variants: list[Request] = []
    version_changed = copy.deepcopy(request)
    version_changed["expected_version"] = request["expected_version"] + 1
    variants.append(version_changed)

    speaker_ids = sorted(aggregate["items"])
    if len(speaker_ids) > 1:
        speaker_changed = copy.deepcopy(request)
        speaker_changed["speaker_id"] = next(
            speaker_id for speaker_id in speaker_ids if speaker_id != request["speaker_id"]
        )
        variants.append(speaker_changed)

    if request["label"] is not None:
        label_changed = copy.deepcopy(request)
        label_changed["label"] = request["label"] + "-variant"
        variants.append(label_changed)

    if request["target_identity_id"] is not None:
        identity_changed = copy.deepcopy(request)
        identity_changed["target_identity_id"] = request["target_identity_id"] + "-variant"
        variants.append(identity_changed)

    baseline = canonical_request_hash(request)
    for variant in data.draw(st.permutations(variants)):
        assert canonical_request_hash(variant) != baseline


async def _persisted_review(db_session: Any) -> tuple[str, str]:
    """Create a minimal, synthetic database-backed review fixture."""
    from datetime import UTC, datetime

    from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem

    meeting_id = "meeting-db-test"
    review_id = "review-db-test"
    db_session.add(Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="completed",
        failure_cause=None,
        created_by="owner-db-test",
        created_at=datetime.now(UTC),
    ))
    db_session.add(SpeakerReview(
        id=review_id,
        meeting_id=meeting_id,
        processing_revision=1,
        status="pending",
        created_at=datetime.now(UTC),
    ))
    db_session.add(SpeakerReviewItem(
        id="item-db-test",
        review_id=review_id,
        speaker_key="speaker-db-test",
        current_label="Speaker 1",
        disposition=None,
        chosen_label=None,
        attribution_state="uncertain",
        version=1,
    ))
    await db_session.flush()
    return meeting_id, review_id


async def test_persistent_disposition_replay_returns_receipt_without_advancing_item_twice(db_session: Any) -> None:
    """A replay reads the durable response and keeps one item transition."""
    from sqlalchemy import select

    from app.infra.models import SpeakerReviewIdempotencyReceipt, SpeakerReviewItem
    from app.meetings.speaker_review_service import SpeakerReviewService

    meeting_id, _ = await _persisted_review(db_session)
    service = SpeakerReviewService(db_session)
    request = {"disposition": "named", "label": "Synthetic person", "expected_version": 1,
               "idempotency_key": "key-db-test"}
    async with db_session.begin_nested():
        applied = await service.record_disposition("owner-db-test", meeting_id, "1", "speaker-db-test", request, 1)
    async with db_session.begin_nested():
        replayed = await service.record_disposition("owner-db-test", meeting_id, "1", "speaker-db-test", request, 1)
    assert applied["outcome"] == "apply"
    assert replayed == {"outcome": "replay", "result": applied["result"]}
    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    receipts = list((await db_session.scalars(select(SpeakerReviewIdempotencyReceipt))).all())
    assert item is not None and item.version == 2 and item.disposition == "named"
    assert len(receipts) == 1


async def test_persistent_stale_version_and_key_hash_reuse_do_not_mutate(db_session: Any) -> None:
    """Persistent conflicts neither advance the item nor add a receipt."""
    from sqlalchemy import select

    from app.infra.models import SpeakerReviewIdempotencyReceipt, SpeakerReviewItem
    from app.meetings.speaker_review_service import SpeakerReviewService

    meeting_id, _ = await _persisted_review(db_session)
    service = SpeakerReviewService(db_session)
    request = {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "key-db-conflict"}
    async with db_session.begin_nested():
        first = await service.record_disposition("owner-db-test", meeting_id, "1", "speaker-db-test", request, 1)
    async with db_session.begin_nested():
        key_conflict = await service.record_disposition("owner-db-test", meeting_id, "1", "speaker-db-test",
            {**request, "disposition": "named", "label": "Changed"}, 1)
    async with db_session.begin_nested():
        stale = await service.record_disposition("owner-db-test", meeting_id, "1", "speaker-db-test",
            {"disposition": "confirmed", "expected_version": 1, "idempotency_key": "new-key"}, 1)
    assert first["outcome"] == "apply"
    assert key_conflict["outcome"] == "conflict_key_hash_mismatch"
    assert stale["outcome"] == "conflict_stale_version"
    item = await db_session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.id == "item-db-test"))
    receipts = list((await db_session.scalars(select(SpeakerReviewIdempotencyReceipt))).all())
    assert item is not None and item.version == 2
    assert len(receipts) == 1
