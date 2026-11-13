"""RED persistence contracts for meeting summaries and personal templates.

Spec: meeting-summaries-templates T1 (#269), design D3–D5/D15, P8 and R6.
Only synthetic rows are used; these tests precede the T2 models and migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import UniqueConstraint, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Meeting,
    MeetingSummary,
    ProcessedSummaryEvent,
    SummaryRequestOutbox,
    SummaryTemplate,
    TemplateCategory,
    Transcript,
    User,
)


def _id() -> str:
    return str(uuid.uuid4())


async def _source(session: AsyncSession, *, category: bool = False) -> tuple[str, str, str, str, str | None]:
    """Persist the existing meeting/transcript and their future owner/template lineage."""
    owner_id, meeting_id, transcript_id, template_id = (_id() for _ in range(4))
    category_id = _id() if category else None
    now = datetime.now(UTC)
    session.add(
        User(
            id=owner_id,
            email=f"{owner_id}@example.test",
            name="Synthetic",
            password_hash="test-hash",
            is_sales=True,
            created_at=now,
        )
    )
    session.add(
        Meeting(
            id=meeting_id,
            meet_link="https://meet.google.com/abc-defg-hij",
            origin="link",
            calendar_invite_id=None,
            scheduled_start_time=None,
            process_state="completed",
            failure_cause=None,
            created_by=owner_id,
            created_at=now,
        )
    )
    session.add(
        Transcript(
            id=transcript_id,
            meeting_id=meeting_id,
            language="es-CO",
            provider="synthetic",
            supports_turns=True,
            expires_at=None,
            created_at=now,
        )
    )
    # When FK enforcement is enabled, flush owners before their dependent rows;
    # scalar FK ids alone do not give the ORM a unit-of-work relationship ordering.
    await session.flush()
    if category_id is not None:
        session.add(TemplateCategory(id=category_id, owner_user_id=owner_id, name="Synthetic category", created_at=now))
        await session.flush()
    session.add(
        SummaryTemplate(
            id=template_id,
            owner_user_id=owner_id,
            category_id=category_id,
            name="Synthetic template",
            version=1,
            instructions="Synthetic instructions",
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    return owner_id, meeting_id, transcript_id, template_id, category_id


def _request_and_summary(
    *, meeting_id: str, transcript_id: str, template_id: str, generation: int, event_id: str
) -> tuple[SummaryRequestOutbox, ProcessedSummaryEvent, MeetingSummary]:
    now = datetime.now(UTC)
    return (
        SummaryRequestOutbox(
            event_id=event_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            template_id=template_id,
            template_version=1,
            instructions_snapshot="Synthetic instructions",
            generation=generation,
            status="succeeded",
            delivered_at=now,
        ),
        ProcessedSummaryEvent(event_id=event_id, meeting_id=meeting_id, completed_at=now),
        MeetingSummary(
            id=_id(),
            event_id=event_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            template_id=template_id,
            template_version=1,
            topic="Synthetic topic",
            key_points_json='["Synthetic point"]',
            generation=generation,
            created_at=now,
            updated_at=now,
        ),
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(owner_id=st.uuids())
@pytest.mark.asyncio
async def test_new_user_has_no_seed_template_or_default(db_session: AsyncSession, owner_id: uuid.UUID) -> None:
    """Schema creation must not insert a template or configure a personal default (D3/P4)."""
    templates_before = (await db_session.scalars(select(SummaryTemplate))).all()
    assert templates_before == []
    user = User(
        id=str(owner_id),
        email=f"{owner_id}@example.test",
        name="Synthetic",
        password_hash="test-hash",
        is_sales=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    assert user.default_summary_template_id is None
    assert (await db_session.scalars(select(SummaryTemplate))).all() == []


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(generations=st.lists(st.integers(min_value=1, max_value=1000), min_size=2, max_size=6, unique=True))
@pytest.mark.asyncio
async def test_distinct_requests_persist_generations_with_category_and_ledger(
    db_session: AsyncSession, generations: list[int]
) -> None:
    """Owner/category/template/outbox/ledger/summary form real persisted FK chains."""
    owner_id, meeting_id, transcript_id, template_id, category_id = await _source(db_session, category=True)
    assert category_id is not None
    event_ids = [_id() for _ in generations]
    for generation, event_id in zip(generations, event_ids, strict=True):
        db_session.add_all(
            _request_and_summary(
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                template_id=template_id,
                generation=generation,
                event_id=event_id,
            )
        )
    await db_session.flush()

    assert (await db_session.get(TemplateCategory, category_id)).owner_user_id == owner_id  # type: ignore[union-attr]
    template = await db_session.get(SummaryTemplate, template_id)
    assert template is not None and template.owner_user_id == owner_id and template.category_id == category_id
    requests = (
        await db_session.scalars(
            select(SummaryRequestOutbox).where(SummaryRequestOutbox.transcript_id == transcript_id)
        )
    ).all()
    summaries = (
        await db_session.scalars(select(MeetingSummary).where(MeetingSummary.transcript_id == transcript_id))
    ).all()
    assert {(row.event_id, row.generation) for row in requests} == set(zip(event_ids, generations, strict=True))
    assert {(row.event_id, row.generation) for row in summaries} == set(zip(event_ids, generations, strict=True))
    assert {
        row.event_id
        for row in (
            await db_session.scalars(
                select(ProcessedSummaryEvent).where(ProcessedSummaryEvent.meeting_id == meeting_id)
            )
        ).all()
    } == set(event_ids)

    # Both the outbox and the artifact reject another event at an occupied generation.
    for model in (SummaryRequestOutbox, MeetingSummary):
        duplicate = _request_and_summary(
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            template_id=template_id,
            generation=generations[0],
            event_id=_id(),
        )
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(duplicate[0] if model is SummaryRequestOutbox else duplicate[2])
                await db_session.flush()

    # Redelivery of an already successful event must not create another summary row.
    duplicate_event = _request_and_summary(
        meeting_id=meeting_id,
        transcript_id=transcript_id,
        template_id=template_id,
        generation=max(generations) + 1,
        event_id=event_ids[0],
    )[2]
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(duplicate_event)
            await db_session.flush()
    assert len(
        (await db_session.scalars(select(MeetingSummary).where(MeetingSummary.transcript_id == transcript_id))).all()
    ) == len(generations)


def test_summary_schema_declares_exact_owner_event_and_transcript_links() -> None:
    """The approved schema has no transcript-only uniqueness and no summary singleton."""
    user_default = next(
        fk
        for fk in User.__table__.c.default_summary_template_id.foreign_keys
        if fk.target_fullname == "summary_templates.id"
    )
    assert user_default.ondelete == "SET NULL"
    assert User.__table__.c.default_summary_template_id.nullable
    for model, field, target in (
        (TemplateCategory, "owner_user_id", "users.id"),
        (SummaryTemplate, "owner_user_id", "users.id"),
        (SummaryTemplate, "category_id", "template_categories.id"),
        (SummaryRequestOutbox, "meeting_id", "meetings.id"),
        (SummaryRequestOutbox, "transcript_id", "transcripts.id"),
        (SummaryRequestOutbox, "template_id", "summary_templates.id"),
        (ProcessedSummaryEvent, "meeting_id", "meetings.id"),
        (MeetingSummary, "meeting_id", "meetings.id"),
        (MeetingSummary, "transcript_id", "transcripts.id"),
        (MeetingSummary, "template_id", "summary_templates.id"),
    ):
        assert any(fk.target_fullname == target for fk in model.__table__.c[field].foreign_keys)
    assert SummaryRequestOutbox.__table__.primary_key.columns.keys() == ["event_id"]
    assert ProcessedSummaryEvent.__table__.primary_key.columns.keys() == ["event_id"]
    for model in (SummaryRequestOutbox, MeetingSummary):
        uniques = {
            frozenset(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert frozenset({"transcript_id", "generation"}) in uniques
        assert frozenset({"transcript_id"}) not in uniques
    assert frozenset({"event_id"}) in {
        frozenset(column.name for column in constraint.columns)
        for constraint in MeetingSummary.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert any(
        fk.target_fullname == "transcripts.id" and fk.ondelete == "CASCADE"
        for fk in MeetingSummary.__table__.c.transcript_id.foreign_keys
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    summary_count=st.integers(min_value=1, max_value=6),
    generation_start=st.integers(min_value=1, max_value=1000),
)
@pytest.mark.asyncio
async def test_deleting_transcript_cascades_every_summary(
    db_session: AsyncSession, summary_count: int, generation_start: int
) -> None:
    """The source transcript's deletion removes all successful generations (R6.1)."""
    # conftest's SQLite in-memory engine does not enable FK enforcement by default.
    # Set it before the first write and verify it; otherwise this test could pass/fail spuriously.
    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert (await db_session.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    _, meeting_id, transcript_id, template_id, _ = await _source(db_session)
    for generation in range(generation_start, generation_start + summary_count):
        db_session.add_all(
            _request_and_summary(
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                template_id=template_id,
                generation=generation,
                event_id=_id(),
            )
        )
    await db_session.commit()
    assert (
        len(
            (
                await db_session.scalars(select(MeetingSummary).where(MeetingSummary.transcript_id == transcript_id))
            ).all()
        )
        == summary_count
    )
    transcript = await db_session.get(Transcript, transcript_id)
    assert transcript is not None
    await db_session.delete(transcript)
    await db_session.commit()
    assert (
        await db_session.scalars(select(MeetingSummary).where(MeetingSummary.transcript_id == transcript_id))
    ).all() == []
