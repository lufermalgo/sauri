"""Read-only projection of confirmed core processing, never a second job state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Diarization, Meeting, MeetingProcessingClaim, SpeechTurn, Transcript


async def processing_snapshot(session: AsyncSession, meeting: Meeting) -> dict[str, Any]:
    """Caller must authorize and lock the meeting before reading its current artifacts."""
    claim = await session.get(MeetingProcessingClaim, meeting.id)
    transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting.id))
    diarization = None
    timings = []
    if transcript is not None:
        diarization = await session.scalar(
            select(Diarization).where(
                Diarization.meeting_id == meeting.id,
                Diarization.transcript_id == transcript.id,
            ).order_by(Diarization.processing_revision.desc()).limit(1)
        )
        timings = list((await session.execute(
            select(SpeechTurn.start_ms, SpeechTurn.end_ms).where(SpeechTurn.transcript_id == transcript.id)
        )).all())

    transcription_state = "unavailable"
    if meeting.process_state == "failed":
        transcription_state = "failed" if meeting.failure_cause == "engine_failure" else "unavailable"
    elif meeting.process_state == "completed" and transcript is not None:
        transcription_state = "completed"
    elif meeting.process_state == "transcribing" and claim is not None:
        transcription_state = "pending"
        expiry = claim.claim_expires_at
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if claim.claim_kind == "transcription":
            # Expired claims do not prove that a worker is still running.
            transcription_state = "active" if expiry is None or expiry > datetime.now(UTC) else "unavailable"

    diarization_state = "pending" if transcription_state in {"pending", "active", "completed"} else "unavailable"
    if transcription_state == "completed" and diarization is not None:
        diarization_state = {
            "pending": "pending", "in_progress": "active", "completed": "completed",
            "failed": "failed", "not_reconstructible": "failed",
        }.get(diarization.diarization_state, "unavailable")

    recovering = claim is not None and claim.claim_kind == "recovery"
    expires_at = transcript.expires_at if transcript else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    artifacts_current = (
        (expires_at is None or expires_at > datetime.now(UTC))
        and diarization is not None and not diarization.is_legacy
    )
    ready = (
        not recovering
        and transcription_state == "completed"
        and diarization_state == "completed"
        and artifacts_current
        and bool(timings)
        and all(start is not None and end is not None and 0 <= start < end for start, end in timings)
    )
    if recovering:
        transcription_state = diarization_state = "unavailable"
    return {
        "meeting_id": meeting.id,
        "execution": {
            "generation": claim.generation if claim else None,
            "transcript_id": transcript.id if transcript else None,
            "diarization_revision": diarization.processing_revision if diarization else None,
        },
        "stages": [
            {"key": "audio_preparation", "state": "unavailable"},
            {"key": "transcription", "state": transcription_state},
            {"key": "diarization", "state": diarization_state},
            {"key": "result_preparation", "state": "completed" if ready else "unavailable"},
        ],
        "ready": ready,
        "failed": not recovering and (meeting.process_state == "failed" or diarization_state == "failed"),
    }
