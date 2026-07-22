"""Expiration calculation for SessionRecording and Transcript (Req. 6.2, 6.6)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.infra.models import SessionRecording, Transcript


def calculate_expiration(created_at: datetime, period: timedelta) -> datetime:
    """Calculates the expiration date: created_at + period.

    Requirements 6.2, 6.6: the expiration date for SessionRecording and
    Transcript is exactly created_at + period.
    """
    return created_at + period


def apply_retention(
    recording: SessionRecording | None,
    transcript: Transcript | None,
    period: timedelta,
) -> None:
    """Sets expires_at on both entities based on their creation timestamps.

    For SessionRecording, finished_at is used as the temporal reference.
    For Transcript, created_at is used.
    """
    if recording:
        recording.expires_at = calculate_expiration(recording.finished_at, period)
    if transcript:
        transcript.expires_at = calculate_expiration(transcript.created_at, period)
