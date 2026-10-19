"""Property test for the diarization state machine.

# Feature: speaker-identification, Property 16: Diarization state machine correctness
Validates: Requirements 9.1, 9.2, 9.3
"""

from __future__ import annotations

from typing import Literal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.state import apply_diarization_event

# ---------------------------------------------------------------------------
# State machine domain
# ---------------------------------------------------------------------------

STATES = ["pending", "in_progress", "completed", "failed"]
TERMINAL_STATES = {"completed", "failed"}
EVENTS = ["start_process", "diarization_completed", "engine_failed"]
SURROGATE_CATEGORY: Literal["Cs"] = "Cs"

# Valid transitions: (current_state, event) -> (new_state, failure_cause)
VALID_TRANSITIONS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("pending", "start_process"): ("in_progress", None),
    ("in_progress", "diarization_completed"): ("completed", None),
    ("in_progress", "engine_failed"): ("failed", "engine_failure"),
}


# ---------------------------------------------------------------------------
# Property 16: Diarization state machine correctness
# Feature: speaker-identification, Property 16: Diarization state machine correctness
# Validates: Requirements 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    current_state=st.sampled_from(STATES),
    event=st.sampled_from(EVENTS),
)
def test_property_16_valid_transitions_produce_correct_state(
    current_state: str, event: str
) -> None:
    """Valid transitions produce the expected state with successful=True."""
    result = apply_diarization_event(current_state, event)
    pair = (current_state, event)

    if pair in VALID_TRANSITIONS:
        expected_new_state, expected_cause = VALID_TRANSITIONS[pair]
        assert result.successful is True, (
            f"Transition ({current_state}, {event}) should be successful"
        )
        assert result.new_state == expected_new_state, (
            f"Expected {expected_new_state}, got {result.new_state}"
        )
        assert result.failure_cause == expected_cause, (
            f"Expected cause {expected_cause}, got {result.failure_cause}"
        )
    else:
        # Invalid transition or terminal state: preserves state, successful=False
        assert result.successful is False, (
            f"Pair ({current_state}, {event}) should NOT be successful"
        )
        assert result.new_state == current_state, (
            f"State should be preserved as {current_state}, "
            f"got {result.new_state}"
        )


@settings(max_examples=100)
@given(
    terminal_state=st.sampled_from(list(TERMINAL_STATES)),
    event=st.sampled_from(EVENTS),
)
def test_property_16_terminal_states_are_immutable(
    terminal_state: str, event: str
) -> None:
    """Terminal states (completed, failed) reject any event."""
    result = apply_diarization_event(terminal_state, event)

    assert result.successful is False, (
        f"Terminal state {terminal_state} should not accept event {event}"
    )
    assert result.new_state == terminal_state, (
        f"Terminal state must be preserved: expected {terminal_state}, "
        f"got {result.new_state}"
    )


@settings(max_examples=100)
@given(
    current_state=st.sampled_from(STATES),
    invalid_event=st.text(
        alphabet=st.characters(
            blacklist_characters="\x00",
            blacklist_categories=(SURROGATE_CATEGORY,),
        ),
        min_size=1,
        max_size=30,
    ).filter(lambda e: e not in EVENTS),
)
def test_property_16_unrecognized_events_reject_transition(
    current_state: str, invalid_event: str
) -> None:
    """Unrecognized events always return successful=False, preserving the state."""
    result = apply_diarization_event(current_state, invalid_event)

    assert result.successful is False, (
        f"Unrecognized event '{invalid_event}' should not succeed "
        f"in state {current_state}"
    )
    assert result.new_state == current_state, (
        f"State should be preserved as {current_state}, "
        f"got {result.new_state}"
    )
