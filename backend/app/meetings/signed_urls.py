"""Lifetime of the signed media links (playback and thumbnails) the API hands out."""

from __future__ import annotations

import os

DEFAULT_SIGNED_URL_TTL_SECONDS = 900
MIN_SIGNED_URL_TTL_SECONDS = 60
MAX_SIGNED_URL_TTL_SECONDS = 3600


def signed_url_ttl_seconds() -> int:
    """Read ``SIGNED_URL_TTL_SECONDS``; an invalid or out-of-range value raises.

    A signed link is a bearer capability, so a typo must never silently lengthen it.
    """
    raw = os.environ.get("SIGNED_URL_TTL_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_SIGNED_URL_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ValueError("SIGNED_URL_TTL_SECONDS must be an integer") from exc
    if not MIN_SIGNED_URL_TTL_SECONDS <= ttl <= MAX_SIGNED_URL_TTL_SECONDS:
        raise ValueError(
            f"SIGNED_URL_TTL_SECONDS must be between {MIN_SIGNED_URL_TTL_SECONDS} "
            f"and {MAX_SIGNED_URL_TTL_SECONDS}"
        )
    return ttl
