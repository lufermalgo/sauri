"""Property test for retention period calculation (expiration.py).

# Feature: meeting-capture-transcription, Property 11: Retention period calculation
Task: 12.2 — Validates: Requirements 6.2
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.retention.expiration import calculate_expiration

date_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2035, 1, 1),
).map(lambda dt: dt.replace(tzinfo=UTC))

period_strategy = st.integers(min_value=0, max_value=3650).map(lambda days: timedelta(days=days))


# ---------------------------------------------------------------------------
# Property 11: Retention period calculation
# Feature: meeting-capture-transcription, Property 11: Retention period calculation
# Validates: Requirements 6.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(created_at=date_strategy, period=period_strategy)
def test_property_11_expiration_is_created_at_plus_period(
    created_at: datetime, period: timedelta
) -> None:
    """expires_at is exactly created_at + period, with no deviation."""
    expires_at = calculate_expiration(created_at, period)

    assert expires_at == created_at + period
    assert (expires_at - created_at) == period
