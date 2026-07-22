"""Data retention period configuration (Req. 6.2, 6.6)."""

import os
from datetime import timedelta

_DEFAULT_RETENTION_DAYS = 90


def get_retention_period() -> timedelta:
    """Reads the retention period from the RETENTION_DAYS environment variable.

    If it's not defined or isn't a valid integer, uses the default value (90 days).
    """
    raw = os.environ.get("RETENTION_DAYS", "")
    try:
        days = int(raw)
    except (ValueError, TypeError):
        days = _DEFAULT_RETENTION_DAYS
    return timedelta(days=days)
