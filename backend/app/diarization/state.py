"""Diarization state machine — pure transition function.

This module implements `apply_diarization_event` as a pure function (no DB
access or side effects). It defines the valid transitions of a
Diarization's own lifecycle and computes the next state given a current
state and a domain event.

This machine is INDEPENDENT of the Meeting's; it does not invoke
`record_transition` nor write to `meetings` or `state_history`.

Requirements: 9.1, 9.2, 9.3
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

STATES: set[str] = {
    "pending",
    "in_progress",
    "completed",
    "failed",
}

TERMINAL_STATES: set[str] = {"completed", "failed"}

VALID_FAILURE_CAUSES: set[str] = {
    "engine_failure",
}

# Transition map: current_state -> {event -> new_state}
VALID_TRANSITIONS: dict[str, dict[str, str]] = {
    "pending": {
        "start_process": "in_progress",
    },
    "in_progress": {
        "diarization_completed": "completed",
        "engine_failed": "failed",
    },
}

# Map of events leading to "failed" -> corresponding failure_cause
EVENT_TO_CAUSE: dict[str, str] = {
    "engine_failed": "engine_failure",
}


# ---------------------------------------------------------------------------
# Transition result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiarizationTransitionResult:
    """Result of applying an event to a diarization state.

    Attributes:
        successful: True if the transition was valid and applied.
        new_state: Resulting state (same as current if successful=False).
        failure_cause: Failure cause if the transition leads to 'failed', None otherwise.
    """

    successful: bool
    new_state: str
    failure_cause: str | None = None


# ---------------------------------------------------------------------------
# Pure transition function
# ---------------------------------------------------------------------------


def apply_diarization_event(
    current_state: str, event: str
) -> DiarizationTransitionResult:
    """Applies an event to the current state and returns the transition result.

    Rules:
    - If `current_state` is terminal (completed/failed): returns successful=False.
    - If `event` is not valid for `current_state`: returns successful=False.
    - If the transition leads to 'failed': includes the corresponding failure_cause.
    - Otherwise: returns the new state with successful=True.

    This function is PURE: it doesn't access a database or produce side
    effects. It only computes the next state.
    """
    # Terminal states: immutable
    if current_state in TERMINAL_STATES:
        return DiarizationTransitionResult(
            successful=False, new_state=current_state
        )

    # Look up valid transitions from the current state
    transitions_from_state = VALID_TRANSITIONS.get(current_state)
    if transitions_from_state is None:
        return DiarizationTransitionResult(
            successful=False, new_state=current_state
        )

    # Look up whether the event is among the valid transitions
    new_state = transitions_from_state.get(event)
    if new_state is None:
        return DiarizationTransitionResult(
            successful=False, new_state=current_state
        )

    # Valid transition — determine failure_cause if applicable
    failure_cause: str | None = None
    if new_state == "failed":
        failure_cause = EVENT_TO_CAUSE.get(event)

    return DiarizationTransitionResult(
        successful=True,
        new_state=new_state,
        failure_cause=failure_cause,
    )
