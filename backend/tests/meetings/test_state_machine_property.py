"""Property tests for the pure ProcessState state machine.

# Feature: meeting-capture-transcription, Property 3: State machine integrity
# Feature: meeting-capture-transcription, Property 4: Every transition to "failed" records a valid cause
Tasks: 5.2, 5.3

Also covers design.md's Propiedad 2 (english-codebase-standard spec): renaming
the state/event literals must not change any transition outcome. Since the
old Spanish-literal function no longer exists to compare against, this is
verified by preserving the exact same assertions against the new English
literals -- an equivalence-preserving rename, not a behavior change.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.meetings.state_machine import (
    EVENT_TO_CAUSE,
    STATES,
    TERMINAL_STATES,
    VALID_FAILURE_CAUSES,
    VALID_TRANSITIONS,
    apply_event,
)

EVENTS = [
    "start_capture",
    "meeting_cancelled",
    "capture_started",
    "join_timeout",
    "recording_uploaded",
    "transcription_completed",
    "engine_failed",
]


# ---------------------------------------------------------------------------
# Property 3: State machine integrity
# Feature: meeting-capture-transcription, Property 3: State machine integrity
# Validates: Requirements 1.4, 1.5, 2.5, 3.6, 4.1, 4.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(current_state=st.sampled_from(sorted(STATES)), event=st.sampled_from(EVENTS))
def test_property_3_only_valid_transitions_produce_a_new_state(
    current_state: str, event: str
) -> None:
    """Only (state, event) pairs defined in VALID_TRANSITIONS produce a new state."""
    result = apply_event(current_state, event)

    assert result.new_state in STATES

    if current_state in TERMINAL_STATES:
        assert result.successful is False
        assert result.new_state == current_state
        return

    expected_transition = VALID_TRANSITIONS.get(current_state, {}).get(event)
    if expected_transition is None:
        assert result.successful is False
        assert result.new_state == current_state
    else:
        assert result.successful is True
        assert result.new_state == expected_transition


@settings(max_examples=100)
@given(terminal_state=st.sampled_from(sorted(TERMINAL_STATES)), event=st.sampled_from(EVENTS))
def test_property_3_terminal_states_are_immutable(
    terminal_state: str, event: str
) -> None:
    """Terminal states (completed, failed) reject any event without changing state."""
    result = apply_event(terminal_state, event)

    assert result.successful is False
    assert result.new_state == terminal_state


# ---------------------------------------------------------------------------
# Property 4: Every transition to "failed" records a valid cause
# Feature: meeting-capture-transcription, Property 4: Every transition to "failed" records a valid cause
# Validates: Requirements 1.6, 3.7, 4.3, 4.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(current_state=st.sampled_from(sorted(STATES)), event=st.sampled_from(EVENTS))
def test_property_4_transition_to_failed_has_a_valid_cause(
    current_state: str, event: str
) -> None:
    """Every successful transition that results in 'failed' records a valid failure_cause."""
    result = apply_event(current_state, event)

    if result.successful and result.new_state == "failed":
        assert result.failure_cause in VALID_FAILURE_CAUSES
        assert result.failure_cause == EVENT_TO_CAUSE.get(event)
    elif result.successful:
        assert result.failure_cause is None
