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
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

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
MeetingInput = CalendarMeetingInput | LinkMeetingInput | ManualMeetingInput


# Identifier accepted in paths and bodies: UUIDs and the readable ids used by seeds and tests.
ResourceId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]

# Largest value of a PostgreSQL INTEGER column (processing revisions).
MAX_INT32 = 2_147_483_647
RevisionId = Annotated[int, Field(ge=1, le=MAX_INT32)]


class MeetingCreate(BaseModel):
    """Wire body of POST /api/v1/meetings.

    The portal sends only ``meet_link``. ``type`` and the calendar fields are the other
    shapes `register_meeting` has always understood; nothing else is accepted.
    """

    model_config = ConfigDict(extra="forbid")

    meet_link: str = Field(max_length=512)
    type: Literal["manual"] | None = None
    calendar_invite_id: str | None = Field(default=None, min_length=1, max_length=256)
    scheduled_start_time: datetime | None = None

    @model_validator(mode="after")
    def validate_calendar_fields(self) -> MeetingCreate:
        if (self.calendar_invite_id is None) != (self.scheduled_start_time is None):
            raise ValueError("calendar_invite_id and scheduled_start_time go together")
        return self
