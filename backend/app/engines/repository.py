"""Writes the provenance of a processing result onto its row.

The same four columns exist on transcripts, diarizations and summaries (migration 027), so one helper
serves every process worker. It records names only, never keys, content or paths.
"""

from __future__ import annotations

from app.engines.routing import Provenance
from app.infra.models import Diarization, MeetingSummary, Transcript

ProvenanceRow = Transcript | Diarization | MeetingSummary

ENGINE_NAME_MAX = 64
ENGINE_MODEL_MAX = 256


def apply_provenance(row: ProvenanceRow, provenance: Provenance) -> None:
    """Record which engine really produced ``row`` and, when the local engine took over, why."""
    row.engine_name = provenance.engine_name[:ENGINE_NAME_MAX] if provenance.engine_name else None
    row.engine_model = provenance.engine_model[:ENGINE_MODEL_MAX] if provenance.engine_model else None
    row.engine_external = provenance.external
    row.engine_fallback_reason = provenance.fallback_reason
