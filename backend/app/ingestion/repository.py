"""Persistence repository for the SessionRecording entity."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import SessionRecording


class RecordingRepository:
    """SQLAlchemy repository for SessionRecording — metadata and blob refs in the ObjectStore."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, recording: SessionRecording) -> SessionRecording:
        """Persists a new session recording."""
        async with self._session_factory() as session:
            session.add(recording)
            await session.commit()
            await session.refresh(recording)
            return recording

    async def get_by_meeting(self, meeting_id: str) -> SessionRecording | None:
        """Gets the recording associated with a meeting."""
        async with self._session_factory() as session:
            stmt = select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def exists_by_idempotency_key(self, key: str) -> bool:
        """Checks whether a recording with the given idempotency key already exists."""
        async with self._session_factory() as session:
            stmt = select(SessionRecording.id).where(
                SessionRecording.idempotency_key == key
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
