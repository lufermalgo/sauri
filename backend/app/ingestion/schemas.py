"""Ingestion contract — Pydantic schema any Meeting_Assistant must satisfy.

The `capture_origin` field records the source (Chrome extension, web upload, or
server bot) but does NOT alter the downstream pipeline (store -> transcribe -> persist).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

# `meetings.id` is a 36-character column (a UUID); the key column holds 256.
MeetingIdField = Annotated[
    str, StringConstraints(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
# Upper bound of a recording the portal could plausibly send: 7 days.
MAX_DURATION_SECONDS = 604_800
MAX_VIDEO_OFFSET_MS = 86_400_000


class IngestionData(BaseModel):
    """Data accompanying the upload of a SessionRecording to the backend.

    This is the common contract that ANY Meeting_Assistant implementation
    (Chrome extension or server bot) must provide alongside the binary files.

    The `capture_origin` field is stored for traceability, but the
    ingestion -> transcription -> persistence pipeline behaves identically
    regardless of its value (Req. 2.1, 2.2).
    """

    model_config = ConfigDict(extra="forbid")

    language: str | None = Field(default=None, pattern=r"^(auto|[a-z]{2})$")

    video_presence: Literal["muxed", "separate", "absent"]
    video_offset_ms: int | None = Field(
        default=None, strict=True, ge=-MAX_VIDEO_OFFSET_MS, le=MAX_VIDEO_OFFSET_MS
    )

    @model_validator(mode="after")
    def validate_video_evidence(self) -> IngestionData:
        if self.video_presence == "separate" and self.video_offset_ms is None:
            raise ValueError("separate video requires a signed video_offset_ms")
        if self.video_presence != "separate" and self.video_offset_ms is not None:
            raise ValueError("video_offset_ms is only valid for separate video")
        return self

    meeting_id: MeetingIdField = Field(
        ...,
        description="Identifier of the Meeting the recording belongs to.",
    )
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description=(
            "Stable key per sessionId/Meeting that allows safe upload "
            "retries without duplicating the SessionRecording."
        ),
    )
    capture_origin: Literal["chrome_extension", "server_bot", "web_upload"] = Field(
        ...,
        description=(
            "Source that produced the recording. Doesn't alter the "
            "behavior of the downstream pipeline."
        ),
    )
    duration_seconds: int = Field(
        ...,
        ge=0,
        le=MAX_DURATION_SECONDS,
        description="Duration in seconds of the captured recording.",
    )
    interrupted: bool = Field(
        default=False,
        description="True if capture was interrupted before the meeting ended (Req. 2.4).",
    )
    notice_issued_at: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "ISO-8601 timestamp when the RecordingNotice was issued. "
            "If provided, the backend records the auditable event (Req. 6.5)."
        ),
    )
    title: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Meeting title (detected by the Meeting_Assistant). "
            "Used only when auto-creating the Meeting if it doesn't exist yet."
        ),
    )
    meet_link: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Actual Google Meet link (detected by the Meeting_Assistant). "
            "Used only when auto-creating the Meeting if it doesn't exist yet."
        ),
    )

    @field_validator("notice_issued_at")
    @classmethod
    def validate_notice_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value)  # the service parses it again; fail here with 422
        return value
