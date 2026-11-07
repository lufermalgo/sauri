"""Property test for the diarization state machine.

# Feature: speaker-identification, Property 16: Diarization state machine correctness
Validates: Requirements 9.1, 9.2, 9.3
"""

from __future__ import annotations

from dataclasses import dataclass
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


# T7 uses a hashable, immutable event as the existing second argument. The
# state machine decides on received evidence; object inspection and persisted
# generation selection are tested at their respective storage/repository/API seams.
@dataclass(frozen=True, slots=True)
class ProcessingEvent:
    kind: str
    failure_cause: str | None = None
    audio_evidence: str | None = None
    retry_requested: bool = False


TERMINAL_AUDIO_EVIDENCE = ("recording_expired", "exact_object_missing")
NONTERMINAL_AUDIO_EVIDENCE = (
    None,
    "unverified_missing",
    "reference_absent",
    "bucket_missing",
    "permission_denied",
    "timeout",
    "invalid_response",
)
RETRYABLE_CAUSES = ("engine_failure", "transient_storage_failure", "timeout")
NONRETRYABLE_CAUSES = (
    "audio_unavailable",
    "permission_denied",
    "unknown",
    None,
)


@settings(max_examples=30)
@given(evidence=st.sampled_from(TERMINAL_AUDIO_EVIDENCE))
def test_t7_confirmed_audio_unavailable_is_terminal(evidence: str) -> None:
    event = ProcessingEvent(
        kind="audio_unavailable",
        failure_cause="audio_unavailable",
        audio_evidence=evidence,
    )
    result = apply_diarization_event("pending", event)
    assert result.successful is True
    assert result.new_state == "not_reconstructible"
    assert result.failure_cause == "audio_unavailable"


@settings(max_examples=40)
@given(
    evidence=st.sampled_from(NONTERMINAL_AUDIO_EVIDENCE),
    cause=st.sampled_from(("audio_unavailable", "engine_failure", None)),
)
def test_t7_unverified_audio_does_not_become_terminal(
    evidence: str | None, cause: str | None
) -> None:
    result = apply_diarization_event(
        "pending",
        ProcessingEvent(
            kind="audio_unavailable", failure_cause=cause, audio_evidence=evidence
        ),
    )
    assert result.successful is False
    assert result.new_state == "pending"


def test_t7_legacy_audio_unavailable_string_is_not_evidence() -> None:
    result = apply_diarization_event("pending", "audio_unavailable")
    assert result.successful is False
    assert result.new_state == "pending"


@settings(max_examples=30)
@given(evidence=st.sampled_from(TERMINAL_AUDIO_EVIDENCE))
def test_t7_terminal_requires_audio_unavailable_cause(evidence: str) -> None:
    result = apply_diarization_event(
        "pending",
        ProcessingEvent(
            kind="audio_unavailable",
            failure_cause="permission_denied",
            audio_evidence=evidence,
        ),
    )
    assert result.successful is False
    assert result.new_state == "pending"


@settings(max_examples=40)
@given(
    event=st.sampled_from(
        (
            ProcessingEvent("audio_unavailable", "audio_unavailable", "exact_object_missing"),
            ProcessingEvent("retry", "engine_failure", retry_requested=True),
            ProcessingEvent("start_process"),
            "start_process",
            "diarization_completed",
            "engine_failed",
        )
    )
)
def test_t7_terminal_state_rejects_redelivery_and_retry(
    event: ProcessingEvent | str,
) -> None:
    result = apply_diarization_event("not_reconstructible", event)
    assert result.successful is False
    assert result.new_state == "not_reconstructible"


@settings(max_examples=40)
@given(cause=st.sampled_from(RETRYABLE_CAUSES))
def test_t7_explicit_retry_of_retryable_failure_returns_pending(cause: str) -> None:
    result = apply_diarization_event(
        "failed", ProcessingEvent("retry", failure_cause=cause, retry_requested=True)
    )
    assert result.successful is True
    assert result.new_state == "pending"
    assert result.failure_cause is None


@settings(max_examples=40)
@given(
    cause=st.sampled_from(RETRYABLE_CAUSES + NONRETRYABLE_CAUSES),
    requested=st.booleans(),
)
def test_t7_retry_requires_explicit_intent_and_retryable_cause(
    cause: str | None, requested: bool
) -> None:
    if requested and cause in RETRYABLE_CAUSES:
        return
    result = apply_diarization_event(
        "failed", ProcessingEvent("retry", failure_cause=cause, retry_requested=requested)
    )
    assert result.successful is False
    assert result.new_state == "failed"


@settings(max_examples=30)
@given(cause=st.sampled_from(RETRYABLE_CAUSES))
def test_t7_failed_does_not_retry_without_retry_event(cause: str) -> None:
    result = apply_diarization_event(
        "failed", ProcessingEvent("engine_failed", failure_cause=cause)
    )
    assert result.successful is False
    assert result.new_state == "failed"
