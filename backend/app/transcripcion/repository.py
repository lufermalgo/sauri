"""Repositorio de persistencia para Transcripcion y TurnoDeHabla."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Transcripcion, TurnoDeHabla


class TranscripcionRepository:
    """Repositorio SQLAlchemy para Transcripcion — metadatos y turnos en una transacción."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def crear(
        self, transcripcion: Transcripcion, turnos: list[TurnoDeHabla]
    ) -> Transcripcion:
        """Persiste una transcripción junto con todos sus turnos de habla en una transacción."""
        async with self._session_factory() as session:
            session.add(transcripcion)
            for turno in turnos:
                session.add(turno)
            await session.commit()
            await session.refresh(transcripcion)
            return transcripcion

    async def obtener_por_reunion(self, reunion_id: str) -> Transcripcion | None:
        """Obtiene la transcripción asociada a una reunión."""
        async with self._session_factory() as session:
            stmt = select(Transcripcion).where(Transcripcion.reunion_id == reunion_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
