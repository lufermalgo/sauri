"""When a recording was made: validation and precedence of the possible sources.

`created_at` is when Sauri received the recording; `recorded_at` is when it was
actually made. The value comes from the best evidence available, and a better
source may replace a weaker one but never the other way round.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final, Literal

RecordedAtSource = Literal["capture", "file_metadata", "file_modified", "received"]

SOURCE_CAPTURE: Final = "capture"
SOURCE_FILE_METADATA: Final = "file_metadata"
SOURCE_FILE_MODIFIED: Final = "file_modified"
SOURCE_RECEIVED: Final = "received"

# A stronger source replaces a weaker one; `received` is only the fallback.
_PRECEDENCE: Final[dict[str, int]] = {
    SOURCE_RECEIVED: 1,
    SOURCE_FILE_MODIFIED: 2,
    SOURCE_FILE_METADATA: 3,
    SOURCE_CAPTURE: 4,
}

MIN_RECORDED_AT: Final = datetime(1990, 1, 1, tzinfo=UTC)
# Browser and server clocks differ a little; anything further ahead is not a recording date.
FUTURE_SKEW: Final = timedelta(minutes=10)


def parse_timestamp(value: str) -> datetime | None:
    """Read an ISO-8601 timestamp (a trailing Z is fine); naive values are taken as UTC."""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def plausible_recorded_at(value: datetime | None, now: datetime | None = None) -> datetime | None:
    """The value in UTC when it can be a recording date (1990 up to now plus a small skew), else None."""
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    reference = now or datetime.now(UTC)
    if moment < MIN_RECORDED_AT or moment > reference + FUTURE_SKEW:
        return None
    return moment


def is_stronger_source(candidate: str, current: str | None) -> bool:
    """True when `candidate` is better evidence than `current` (a missing source is the weakest)."""
    return _PRECEDENCE.get(candidate, 0) > _PRECEDENCE.get(current or "", 0)
