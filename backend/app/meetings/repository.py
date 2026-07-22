"""Persistence repository for the Meeting entity."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting


class MeetingRepository:
    """SQLAlchemy repository for Meeting — stores metadata and object references."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, meeting: Meeting) -> Meeting:
        """Persists a new meeting."""
        async with self._session_factory() as session:
            session.add(meeting)
            await session.commit()
            await session.refresh(meeting)
            return meeting

    async def get_by_id(self, meeting_id: str) -> Meeting | None:
        """Gets a meeting by its primary key."""
        async with self._session_factory() as session:
            return await session.get(Meeting, meeting_id)

    async def update_state(
        self, meeting_id: str, state: str, failure_cause: str | None = None
    ) -> None:
        """Updates the process_state and optionally the failure_cause of a meeting."""
        async with self._session_factory() as session:
            stmt = (
                update(Meeting)
                .where(Meeting.id == meeting_id)
                .values(process_state=state, failure_cause=failure_cause)
            )
            await session.execute(stmt)
            await session.commit()
