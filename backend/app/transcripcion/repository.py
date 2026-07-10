"""Repositorio de persistencia para Transcripcion y TurnoDeHabla."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.infra.models import Transcripcion, TurnoDeHabla


class TranscripcionRepository:
    """Repositorio SQLAlchemy para Transcripcion — metadatos y turnos en una transacción."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def crear(
        self,
        session: AsyncSession,
        transcripcion: Transcripcion,
        turnos: list[TurnoDeHabla],
    ) -> Transcripcion:
        """Agrega una transcripción y sus turnos de habla a la sesión provista.

        No abre, cierra ni confirma la sesión: el llamador (worker) controla
        la transacción y decidirá cuándo hacer commit o rollback.
        """
        session.add(transcripcion)
        for turno in turnos:
            session.add(turno)
        return transcripcion

    async def obtener_por_reunion(self, reunion_id: str) -> Transcripcion | None:
        """Obtiene la transcripción asociada a una reunión junto con sus turnos."""
        async with self._session_factory() as session:
            stmt = (
                select(Transcripcion)
                .where(Transcripcion.reunion_id == reunion_id)
                .options(selectinload(Transcripcion.turnos))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
