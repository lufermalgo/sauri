"""Persistence repository for Transcript and SpeechTurn."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.infra.models import SpeechTurn, Transcript


class TranscriptRepository:
    """SQLAlchemy repository for Transcript — metadata and turns in one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        session: AsyncSession,
        transcript: Transcript,
        turns: list[SpeechTurn],
    ) -> Transcript:
        """Adds a transcript and its speech turns to the given session.

        Doesn't open, close, or commit the session: the caller (worker)
        controls the transaction and decides when to commit or roll back, so
        a later failure (e.g. the state transition) can revert both the
        Transcript and its SpeechTurn rows atomically.
        """
        session.add(transcript)
        for turn in turns:
            session.add(turn)
        await session.flush()
        return transcript

    async def get_by_meeting(self, meeting_id: str) -> Transcript | None:
        """Gets the transcript associated with a meeting along with its turns."""
        async with self._session_factory() as session:
            stmt = (
                select(Transcript)
                .where(Transcript.meeting_id == meeting_id)
                .options(selectinload(Transcript.turns))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
