"""Lifetimes of the signed media links the API hands out.

Two classes of link, two settings:

* Thumbnails and other short-lived capabilities: ``SIGNED_URL_TTL_SECONDS`` (15 min).
* Playback media: ``PLAYBACK_URL_TTL_SECONDS`` (4 h). The player streams one signed URL
  with HTTP range requests; once it expires, buffering and seeking get 403. A recording
  can exceed an hour (the longest measured is 94 min), so the link must outlive a whole
  viewing session until the player can refresh its own links.
* Download links: ``DOWNLOAD_URL_TTL_SECONDS`` (5 min). The browser follows the link the
  moment the API returns it; the signature is only checked when the transfer starts.
"""

from __future__ import annotations

import os

DEFAULT_SIGNED_URL_TTL_SECONDS = 900
MIN_SIGNED_URL_TTL_SECONDS = 60
MAX_SIGNED_URL_TTL_SECONDS = 3600

DEFAULT_PLAYBACK_URL_TTL_SECONDS = 14_400
MIN_PLAYBACK_URL_TTL_SECONDS = 300
MAX_PLAYBACK_URL_TTL_SECONDS = 43_200

DEFAULT_DOWNLOAD_URL_TTL_SECONDS = 300
MIN_DOWNLOAD_URL_TTL_SECONDS = 60
MAX_DOWNLOAD_URL_TTL_SECONDS = 3600


def _ttl_from_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer lifetime; an invalid or out-of-range value raises.

    A signed link is a bearer capability, so a typo must never silently lengthen it.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= ttl <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return ttl


def signed_url_ttl_seconds() -> int:
    """Lifetime of thumbnail links and other short-lived capabilities."""
    return _ttl_from_env(
        "SIGNED_URL_TTL_SECONDS",
        DEFAULT_SIGNED_URL_TTL_SECONDS,
        MIN_SIGNED_URL_TTL_SECONDS,
        MAX_SIGNED_URL_TTL_SECONDS,
    )


def playback_url_ttl_seconds() -> int:
    """Lifetime of the signed playback media links."""
    return _ttl_from_env(
        "PLAYBACK_URL_TTL_SECONDS",
        DEFAULT_PLAYBACK_URL_TTL_SECONDS,
        MIN_PLAYBACK_URL_TTL_SECONDS,
        MAX_PLAYBACK_URL_TTL_SECONDS,
    )


def download_url_ttl_seconds() -> int:
    """Lifetime of the signed attachment download links."""
    return _ttl_from_env(
        "DOWNLOAD_URL_TTL_SECONDS",
        DEFAULT_DOWNLOAD_URL_TTL_SECONDS,
        MIN_DOWNLOAD_URL_TTL_SECONDS,
        MAX_DOWNLOAD_URL_TTL_SECONDS,
    )
