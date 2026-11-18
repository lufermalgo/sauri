"""Read-only in-flight query shared by local status and the deployment guard.

Keep imports light: pipeline_admission.py prints the SQL with the host's Python,
without requiring the backend's installed dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Preserve every guard predicate; keep full ids so status can count distinct busy meetings.
INFLIGHT_QUERY = """
SELECT 'meeting' AS kind, m.id AS meeting_id, m.process_state AS state,
       max(h.occurred_at) AS since
  FROM meetings m LEFT JOIN state_history h ON h.meeting_id = m.id
 WHERE m.process_state NOT IN ('completed', 'failed') GROUP BY m.id, m.process_state
UNION ALL
SELECT 'speakers', meeting_id, diarization_state, updated_at
  FROM diarizations WHERE diarization_state IN ('pending', 'in_progress')
UNION ALL
SELECT 'summary', meeting_id, status,
       coalesce(started_at, requested_at)
  FROM summary_request_outbox WHERE status IN ('pending', 'running')
UNION ALL
SELECT 'live-claim', meeting_id, claim_kind, claim_expires_at
  FROM meeting_processing_claims
 WHERE claim_kind IN ('transcription', 'diarization') AND claim_expires_at > CURRENT_TIMESTAMP
""".strip()


# Keep the guard's original short ids and UTC display without duplicating its selection rules.
DEPLOY_GUARD_QUERY = f"""
SELECT kind, substr(meeting_id, 1, 8), state,
       coalesce(to_char(since AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), '?')
  FROM ({INFLIGHT_QUERY}) AS inflight
 ORDER BY 1, 4;
""".strip()


async def count_processing(session: AsyncSession) -> int:
    """Count distinct busy meetings, including work after a meeting reached a terminal state."""
    from sqlalchemy import text

    result = await session.execute(text(f"SELECT count(DISTINCT meeting_id) FROM ({INFLIGHT_QUERY}) AS inflight"))
    return int(result.scalar_one())
