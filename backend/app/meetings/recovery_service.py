"""Fail-closed manual recovery precursor (fix-stale-meeting-recovery T-4)."""

from __future__ import annotations

from typing import Literal, TypedDict


class DisabledRecoveryResult(TypedDict):
    """Finite response without artifact, object, or operation content."""

    status: Literal["pilot_not_armed"]
    reason_code: Literal["pilot_not_armed"]


class MeetingRecoveryService:
    """Refuse recovery until the guarded acceptance boundary is implemented.

    This precursor cannot arm a pilot or enqueue work, even if an environment
    variable requests pilot mode. T-18 replaces this refusal only after its
    eligibility, durable-fence, and atomic pilot-gate contracts are verified.
    Meeting authorization remains the route's responsibility.
    """

    async def recover(
        self, meeting_id: str, actor_id: str, idempotency_key: str,
    ) -> DisabledRecoveryResult:
        """Return a real disabled-mode no-op; never claim successful recovery."""
        return {"status": "pilot_not_armed", "reason_code": "pilot_not_armed"}
