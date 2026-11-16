"""``apply_provenance`` writes the same four columns on transcripts, diarizations and summaries."""

from datetime import UTC, datetime

import pytest

from app.engines.repository import apply_provenance
from app.engines.routing import Provenance
from app.infra.models import Diarization, MeetingSummary, Transcript


def rows() -> list[Transcript | Diarization | MeetingSummary]:
    now = datetime.now(UTC)
    return [
        Transcript(id="t", meeting_id="m", provider="p", supports_turns=False, created_at=now),
        Diarization(id="d", meeting_id="m", created_at=now, updated_at=now),
        MeetingSummary(id="s", event_id="e", meeting_id="m", transcript_id="t", template_id="x", template_version=1,
                       topic="t", key_points_json="[]", generation=1, created_at=now, updated_at=now),
    ]


@pytest.mark.parametrize("row", rows(), ids=lambda row: type(row).__name__)
def test_the_real_engine_and_the_fallback_reason_are_recorded(row: Transcript | Diarization | MeetingSummary) -> None:
    apply_provenance(row, Provenance("llama.cpp", "qwen3.5-9b", False, "provider_unavailable"))
    assert (row.engine_name, row.engine_model, row.engine_external, row.engine_fallback_reason) == (
        "llama.cpp", "qwen3.5-9b", False, "provider_unavailable",
    )


@pytest.mark.parametrize("row", rows(), ids=lambda row: type(row).__name__)
def test_names_are_cut_to_their_columns_and_unknown_names_stay_empty(
    row: Transcript | Diarization | MeetingSummary,
) -> None:
    apply_provenance(row, Provenance("n" * 100, "m" * 400, True))
    assert (len(row.engine_name or ""), len(row.engine_model or ""), row.engine_external) == (64, 256, True)
    apply_provenance(row, Provenance(None, None, False))
    assert (row.engine_name, row.engine_model, row.engine_external, row.engine_fallback_reason) == (
        None, None, False, None,
    )
