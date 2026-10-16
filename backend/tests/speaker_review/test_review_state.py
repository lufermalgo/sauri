"""Property tests for recording-scoped speaker review state.

The prospective pure domain seam returns a new mapping rather than mutating its
input: ``set_disposition(state, speaker_id, disposition) -> state``. State is a
synthetic mapping from each speaker ID in one recording revision to either
``None`` or one valid disposition. The function must preserve every other key
and value. Review completion is derived solely from this mapping.

Feature: recording-speaker-review, T-1 RED
Validates: Requirements 3.3–3.7 and 4.1–4.4
"""

from __future__ import annotations

from typing import TypeAlias

from hypothesis import given, settings
from hypothesis import strategies as st

Disposition: TypeAlias = str
VALID_DISPOSITIONS: tuple[Disposition, ...] = ("named", "corrected", "confirmed")
SpeakerState: TypeAlias = dict[str, Disposition | None]


@st.composite
def speaker_states(draw: st.DrawFn) -> SpeakerState:
    """Generate a non-empty synthetic review with unique speaker identifiers."""
    speaker_ids = draw(
        st.lists(
            st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1),
            min_size=1,
            max_size=12,
            unique=True,
        )
    )
    statuses = draw(
        st.lists(
            st.one_of(st.none(), st.sampled_from(VALID_DISPOSITIONS)),
            min_size=len(speaker_ids),
            max_size=len(speaker_ids),
        )
    )
    return dict(zip(speaker_ids, statuses, strict=True))


@settings(max_examples=100)
@given(state=speaker_states(), data=st.data(), disposition=st.sampled_from(VALID_DISPOSITIONS))
def test_domain_disposition_isolation(
    state: SpeakerState, data: st.DataObject, disposition: Disposition
) -> None:
    """Recording a disposition returns new state and leaves non-target items unchanged."""
    from app.meetings.speaker_review_state import set_disposition

    target_speaker_id = data.draw(st.sampled_from(sorted(state)))
    original = state.copy()

    updated = set_disposition(state, target_speaker_id, disposition)

    assert state == original, "the input aggregate must not be mutated"
    assert updated is not state
    assert set(updated) == set(original)
    assert updated[target_speaker_id] == disposition
    for speaker_id, prior_disposition in original.items():
        if speaker_id != target_speaker_id:
            assert updated[speaker_id] == prior_disposition


@settings(max_examples=100)
@given(state=speaker_states())
def test_domain_derived_completion(
    state: SpeakerState,
) -> None:
    """A review is complete iff all items have one valid non-null disposition."""
    from app.meetings.speaker_review_state import is_complete

    assert is_complete(state) is all(
        disposition in VALID_DISPOSITIONS for disposition in state.values()
    )


def test_review_put_schema_excludes_completion() -> None:
    """The public disposition request schema must not expose derived completion."""
    from app.main import app

    schema = app.openapi()
    operation = schema["paths"][
        "/api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}"
    ]["put"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    if "$ref" in request_schema:
        ref_name = request_schema["$ref"].rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][ref_name]

    properties = request_schema.get("properties", {})
    assert "status" not in properties
    assert "complete" not in properties
    assert "is_complete" not in properties
