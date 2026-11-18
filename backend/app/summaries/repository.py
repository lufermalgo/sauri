"""Request persistence; the caller owns the transaction."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.copy.speaker_labels import speaker_label, unknown_speaker_label
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingSummary,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
)
from app.summaries.passages import Passage, Turn, build_passages
from app.templates.seed import ensure_default

ACTIVE_STATUSES = ("pending", "running")


async def current_summary_for_owner(
    session: AsyncSession,
    meeting_id: str,
    owner_id: str,
) -> tuple[MeetingSummary, str] | None:
    """Read the highest successful artifact without consulting newer pending/failed requests."""
    row = (
        await session.execute(
            select(MeetingSummary, SummaryTemplate.name)
            .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
            .join(SummaryTemplate, MeetingSummary.template_id == SummaryTemplate.id)
            .where(Meeting.id == meeting_id, Meeting.created_by == owner_id)
            .order_by(MeetingSummary.generation.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


async def owned_meeting_locked(session: AsyncSession, meeting_id: str, owner_id: str) -> Meeting | None:
    # Serializes generation allocation on PostgreSQL, including the first request.
    return cast(
        Meeting | None,
        await session.scalar(
            select(Meeting)
            .where(
                Meeting.id == meeting_id,
                Meeting.created_by == owner_id,
            )
            .with_for_update()
        ),
    )


async def transcript_for_meeting(session: AsyncSession, meeting_id: str) -> Transcript | None:
    return cast(Transcript | None, await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id)))


async def selected_template(
    session: AsyncSession,
    owner_id: str,
    explicit_id: str | None,
) -> SummaryTemplate | None:
    template_id = explicit_id
    if template_id is None:
        template_id = await ensure_default(session, owner_id)
    if template_id is None:
        return None
    return cast(
        SummaryTemplate | None,
        await session.scalar(
            select(SummaryTemplate).where(
                SummaryTemplate.id == template_id,
                SummaryTemplate.owner_user_id == owner_id,
            )
        ),
    )


async def next_generation(session: AsyncSession, transcript_id: str) -> int:
    latest = await session.scalar(
        select(func.max(SummaryRequestOutbox.generation)).where(
            SummaryRequestOutbox.transcript_id == transcript_id,
        )
    )
    return (latest or 0) + 1


async def active_request(session: AsyncSession, transcript_id: str) -> SummaryRequestOutbox | None:
    """The newest request still waiting for or undergoing generation, if any."""
    return cast(
        SummaryRequestOutbox | None,
        await session.scalar(
            select(SummaryRequestOutbox)
            .where(
                SummaryRequestOutbox.transcript_id == transcript_id,
                SummaryRequestOutbox.status.in_(ACTIVE_STATUSES),
            )
            .order_by(SummaryRequestOutbox.generation.desc())
            .limit(1)
        ),
    )


async def latest_request(session: AsyncSession, transcript_id: str) -> SummaryRequestOutbox | None:
    """The newest request of any status, or None when the transcript never had one."""
    return cast(
        SummaryRequestOutbox | None,
        await session.scalar(
            select(SummaryRequestOutbox)
            .where(SummaryRequestOutbox.transcript_id == transcript_id)
            .order_by(SummaryRequestOutbox.generation.desc())
            .limit(1)
        ),
    )


async def request_for_owner(
    session: AsyncSession,
    meeting_id: str,
    owner_id: str,
    event_id: str | None = None,
) -> SummaryRequestOutbox | None:
    query = (
        select(SummaryRequestOutbox)
        .join(Meeting, SummaryRequestOutbox.meeting_id == Meeting.id)
        .where(Meeting.id == meeting_id, Meeting.created_by == owner_id)
    )
    if event_id is not None:
        query = query.where(SummaryRequestOutbox.event_id == event_id)
    else:
        query = query.order_by(SummaryRequestOutbox.generation.desc()).limit(1)
    return cast(SummaryRequestOutbox | None, await session.scalar(query))


async def locked_request(session: AsyncSession, event_id: str) -> SummaryRequestOutbox | None:
    """Serialize state changes and idempotent commits for one event."""
    return (
        await session.scalars(
            select(SummaryRequestOutbox).where(SummaryRequestOutbox.event_id == event_id).with_for_update()
        )
    ).first()


async def transcript_passages(session: AsyncSession, transcript_id: str) -> list[Passage]:
    language = await session.scalar(select(Transcript.language).where(Transcript.id == transcript_id)) or "es"
    revision = (
        select(Diarization.id)
        .where(Diarization.transcript_id == transcript_id, Diarization.diarization_state == "completed")
        .order_by(Diarization.processing_revision.desc())
        .limit(1).scalar_subquery()
    )
    rows = (await session.execute(
        select(SpeechTurn, Speaker.sequence).select_from(SpeechTurn)
        .outerjoin(SpeakerAssignment, and_(
            SpeakerAssignment.turn_id == SpeechTurn.id, SpeakerAssignment.diarization_id == revision,
        ))
        .outerjoin(Speaker, Speaker.id == SpeakerAssignment.speaker_id)
        .where(SpeechTurn.transcript_id == transcript_id)
        .order_by(SpeechTurn.sequence)
    )).all()
    return build_passages([
        Turn(
            turn.text, turn.start_ms, turn.end_ms,
            speaker_label(speaker, language) if speaker is not None else unknown_speaker_label(language),
        )
        for turn, speaker in rows
    ])


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def speaker_names_for_summary(session: AsyncSession, summary: MeetingSummary) -> tuple[str, dict[int, str]]:
    """The transcript language and the chosen name of each speaker number, for reading a summary.

    Numbers and names come from the latest completed diarization (the one ``transcript_passages`` numbers
    speakers with) and its speaker review. Stale rule: the summary's numbering is only trusted when that
    diarization was completed (``updated_at``) no later than the summary's request was first taken by the
    worker (``started_at``, falling back to ``created_at`` for rows without it). Every attempt builds the
    passages after that moment, so none of them can have seen a newer diarization; otherwise the summary may
    use another numbering and no name is applied, because a missing name is better than a wrong one.
    """
    language = await session.scalar(select(Transcript.language).where(Transcript.id == summary.transcript_id)) or "es"
    diarization = await session.scalar(
        select(Diarization)
        .where(Diarization.transcript_id == summary.transcript_id, Diarization.diarization_state == "completed")
        .order_by(Diarization.processing_revision.desc())
        .limit(1)
    )
    if diarization is None:
        return language, {}
    started_at = await session.scalar(
        select(SummaryRequestOutbox.started_at).where(SummaryRequestOutbox.event_id == summary.event_id)
    )
    if _aware(diarization.updated_at) > _aware(started_at or summary.created_at):
        return language, {}
    rows = (
        await session.execute(
            select(Speaker.sequence, SpeakerReviewItem.chosen_label)
            .join(SpeakerReviewItem, SpeakerReviewItem.speaker_key == Speaker.id)
            .join(SpeakerReview, SpeakerReview.id == SpeakerReviewItem.review_id)
            .where(
                Speaker.diarization_id == diarization.id,
                SpeakerReview.meeting_id == diarization.meeting_id,
                SpeakerReview.processing_revision == diarization.processing_revision,
            )
        )
    ).all()
    return language, {sequence: name for sequence, name in rows if name and name.strip()}
