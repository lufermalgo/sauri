"""Pydantic schemas for validating meeting input.

Defines the three accepted input types for registering a Meeting:
- LinkMeetingInput: only a Google Meet link.
- CalendarMeetingInput: link + calendar invite id + start time.
- ManualMeetingInput: manual request with a Google Meet link.

Requirements: 1.1, 1.7
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Union

from pydantic import BaseModel, field_validator

# Pattern for valid Google Meet links
_MEET_PATTERN = re.compile(r"^https://meet\.google\.com/.+")


def _validate_meet_link(link: str) -> str:
    """Validates that the link starts with https://meet.google.com/."""
    if not _MEET_PATTERN.match(link):
        raise ValueError(
            "The link must start with 'https://meet.google.com/'"
        )
    return link


class LinkMeetingInput(BaseModel):
    """Meeting input via a direct Google Meet link."""

    meet_link: str

    @field_validator("meet_link")
    @classmethod
    def validate_link(cls, v: str) -> str:
        return _validate_meet_link(v)


class CalendarMeetingInput(BaseModel):
    """Meeting input via a calendar invite with a Meet link."""

    meet_link: str
    calendar_invite_id: str
    scheduled_start_time: datetime

    @field_validator("meet_link")
    @classmethod
    def validate_link(cls, v: str) -> str:
        return _validate_meet_link(v)


class ManualMeetingInput(BaseModel):
    """Meeting input via a manual request with a Google Meet link."""

    meet_link: str

    @field_validator("meet_link")
    @classmethod
    def validate_link(cls, v: str) -> str:
        return _validate_meet_link(v)


# Union type — accepts any of the three input types
MeetingInput = Union[CalendarMeetingInput, LinkMeetingInput, ManualMeetingInput]
