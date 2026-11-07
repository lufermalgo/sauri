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
from typing import Protocol

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

STATES: set[str] = {
    "pending",
    "in_progress",
    "completed",
    "failed",
    "not_reconstructible",
}

TERMINAL_STATES: set[str] = {"completed", "not_reconstructible"}

RETRYABLE_FAILURE_CAUSES: set[str] = {
    "engine_failure",
    "transient_storage_failure",
    "timeout",
}

VALID_FAILURE_CAUSES: set[str] = RETRYABLE_FAILURE_CAUSES | {
    "audio_unavailable",
}

TERMINAL_AUDIO_EVIDENCE: set[str] = {
    "recording_expired",
    "exact_object_missing",
}


class StructuredDiarizationEvent(Protocol):
    """Immutable event data used for evidence-gated state transitions."""

    @property
    def kind(self) -> str: ...

    @property
    def failure_cause(self) -> str | None: ...

    @property
    def audio_evidence(self) -> str | None: ...

    @property
    def retry_requested(self) -> bool: ...

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
    current_state: str, event: str | StructuredDiarizationEvent
) -> DiarizationTransitionResult:
    """Applies a legacy string or structured event to a diarization state.

    Structured events carry evidence and retry intent, but this pure function
    does not authenticate storage evidence or read persisted generations.
    """
    event_kind = event if isinstance(event, str) else getattr(event, "kind", None)
    failure_cause = (
        None if isinstance(event, str) else getattr(event, "failure_cause", None)
    )
    audio_evidence = (
        None if isinstance(event, str) else getattr(event, "audio_evidence", None)
    )
    retry_requested = (
        False if isinstance(event, str) else getattr(event, "retry_requested", False)
    )

    if current_state in TERMINAL_STATES or current_state not in STATES:
        return DiarizationTransitionResult(successful=False, new_state=current_state)

    if current_state == "failed":
        if (
            event_kind == "retry"
            and retry_requested is True
            and failure_cause in RETRYABLE_FAILURE_CAUSES
        ):
            return DiarizationTransitionResult(successful=True, new_state="pending")
        return DiarizationTransitionResult(successful=False, new_state=current_state)

    if current_state in {"pending", "in_progress"} and event_kind == "audio_unavailable":
        if (
            failure_cause == "audio_unavailable"
            and audio_evidence in TERMINAL_AUDIO_EVIDENCE
        ):
            return DiarizationTransitionResult(
                successful=True,
                new_state="not_reconstructible",
                failure_cause="audio_unavailable",
            )
        return DiarizationTransitionResult(successful=False, new_state=current_state)

    transitions_from_state = VALID_TRANSITIONS.get(current_state)
    if transitions_from_state is None or not isinstance(event_kind, str):
        return DiarizationTransitionResult(successful=False, new_state=current_state)

    new_state = transitions_from_state.get(event_kind)
    if new_state is None:
        return DiarizationTransitionResult(successful=False, new_state=current_state)

    transition_failure_cause: str | None = None
    if new_state == "failed":
        transition_failure_cause = EVENT_TO_CAUSE.get(event_kind)

    return DiarizationTransitionResult(
        successful=True,
        new_state=new_state,
        failure_cause=transition_failure_cause,
    )
