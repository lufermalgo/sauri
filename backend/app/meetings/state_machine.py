"""ProcessState state machine — pure transition function.

This module implements `apply_event` as a pure function (no DB access or
side effects). It defines the valid transitions from the design's state
diagram and computes the next state given a current state and a domain
event.

Requirements: 1.4, 1.5, 2.5, 3.6, 4.1, 4.2, 4.4
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

STATES: set[str] = {
    "queued",
    "joining",
    "recording",
    "transcribing",
    "completed",
    "failed",
}

TERMINAL_STATES: set[str] = {"completed", "failed"}

VALID_FAILURE_CAUSES: set[str] = {
    "could_not_join",
    "meeting_cancelled",
    "engine_failure",
}

# Transition map: current_state -> {event -> new_state}
VALID_TRANSITIONS: dict[str, dict[str, str]] = {
    "queued": {
        "start_capture": "joining",
        "meeting_cancelled": "failed",
    },
    "joining": {
        "capture_started": "recording",
        "join_timeout": "failed",
    },
    "recording": {
        "recording_uploaded": "transcribing",
    },
    "transcribing": {
        "transcription_completed": "completed",
        "engine_failed": "failed",
    },
}

# Map of events leading to "failed" -> corresponding failure_cause
EVENT_TO_CAUSE: dict[str, str] = {
    "meeting_cancelled": "meeting_cancelled",
    "join_timeout": "could_not_join",
    "engine_failed": "engine_failure",
}


# ---------------------------------------------------------------------------
# Transition result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Result of applying an event to a state.

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


def apply_event(current_state: str, event: str) -> TransitionResult:
    """Applies an event to the current state and returns the transition result.

    Rules:
    - If `current_state` is terminal (completed/failed): returns successful=False.
    - If `event` isn't valid for `current_state`: returns successful=False.
    - If the transition leads to 'failed': includes the corresponding failure_cause.
    - Otherwise: returns the new state with successful=True.

    This function is PURE: it doesn't access the database or produce side
    effects. It only computes the next state.
    """
    # Terminal states: immutable
    if current_state in TERMINAL_STATES:
        return TransitionResult(successful=False, new_state=current_state)

    # Look up valid transitions from the current state
    transitions_from_state = VALID_TRANSITIONS.get(current_state)
    if transitions_from_state is None:
        return TransitionResult(successful=False, new_state=current_state)

    # Check whether the event is among the valid transitions
    new_state = transitions_from_state.get(event)
    if new_state is None:
        return TransitionResult(successful=False, new_state=current_state)

    # Valid transition — determine failure_cause if applicable
    failure_cause: str | None = None
    if new_state == "failed":
        failure_cause = EVENT_TO_CAUSE.get(event)

    return TransitionResult(
        successful=True,
        new_state=new_state,
        failure_cause=failure_cause,
    )
