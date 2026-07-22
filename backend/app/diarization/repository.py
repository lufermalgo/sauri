"""Persistence repository for Diarization, Speaker, and SpeakerAssignment.

Persists the full diarization graph in a single transaction (controlled by
the worker) and retrieves it by meeting_id with eager loading (selectinload).

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.5, 10.6
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.infra.models import Diarization, Speaker, SpeakerAssignment


class DiarizationRepository:
    """SQLAlchemy repository for Diarization — entities in one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        session: AsyncSession,
        diarization: Diarization,
        speakers: list[Speaker],
        assignments: list[SpeakerAssignment],
    ) -> Diarization:
        """Adds the Diarization, its Speakers, and Assignments to the given session.

        Doesn't open, close, or commit the session: the caller (worker)
        controls the transaction and decides when to commit or roll back. A
        failure in any write rolls back everything (atomicity, Req. 8.2, 8.3, 10.6).
        """
        session.add(diarization)
        for speaker in speakers:
            session.add(speaker)
        for assignment in assignments:
            session.add(assignment)
        return diarization

    async def get_by_meeting(self, meeting_id: str) -> Diarization | None:
        """Gets a meeting's Diarization along with its Speakers and Assignments.

        Returns None if it doesn't exist (Req. 8.6). Uses eager loading with
        selectinload to avoid lazy-loading outside the session (Req. 8.5).
        """
        async with self._session_factory() as session:
            stmt = (
                select(Diarization)
                .where(Diarization.meeting_id == meeting_id)
                .options(
                    selectinload(Diarization.speakers),
                    selectinload(Diarization.assignments),
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
