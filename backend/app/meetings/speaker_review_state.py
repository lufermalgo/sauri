"""Speaker-review state — pure domain functions.

This module implements the recording-scoped review aggregate as pure
functions over a mapping of speaker key -> disposition (``None`` while
undisposed). Review status is derived exclusively from item dispositions;
there is no user-editable completion flag.

Requirements: 3.3–3.7, 4.1–4.4
Feature: recording-speaker-review, T-10 GREEN (Issue #243)
"""

from __future__ import annotations

from typing import TypeAlias

Disposition: TypeAlias = str

VALID_DISPOSITIONS: tuple[Disposition, ...] = ("named", "corrected", "confirmed")

SpeakerState: TypeAlias = dict[str, Disposition | None]


def set_disposition(
    state: SpeakerState, speaker_id: str, disposition: Disposition
) -> SpeakerState:
    """Return a new review state with ``disposition`` recorded for ``speaker_id``.

    The input aggregate is never mutated. Every other speaker key keeps its
    prior disposition, so recording one item cannot change another item.

    Raises:
        KeyError: if ``speaker_id`` is not a speaker key of this review.
        ValueError: if ``disposition`` is not one of ``VALID_DISPOSITIONS``.
    """
    if disposition not in VALID_DISPOSITIONS:
        raise ValueError(f"invalid disposition: {disposition!r}")
    if speaker_id not in state:
        raise KeyError(f"unknown speaker key: {speaker_id!r}")

    updated: SpeakerState = dict(state)
    updated[speaker_id] = disposition
    return updated


def is_complete(state: SpeakerState) -> bool:
    """Return ``True`` iff every item carries one valid non-null disposition."""
    return all(disposition in VALID_DISPOSITIONS for disposition in state.values())


def review_status(state: SpeakerState) -> str:
    """Derive the aggregate review status from its items."""
    return "complete" if is_complete(state) else "pending"
