"""Regression tests for the shared Hypothesis profile."""

from hypothesis import settings


def test_sauri_profile_disables_wall_clock_deadline_without_reducing_examples() -> None:
    """Async DB properties are timing-variable; retain 100 examples, no deadline."""
    assert settings.default.max_examples == 100
    assert settings.default.deadline is None
