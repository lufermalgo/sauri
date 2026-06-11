"""Repositorio de persistencia para la entidad Reunion."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Reunion


class ReunionRepository:
    """Repositorio SQLAlchemy para Reunion — guarda metadatos y referencias a objetos."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def crear(self, reunion: Reunion) -> Reunion:
        """Persiste una nueva reunión."""
        async with self._session_factory() as session:
            session.add(reunion)
            await session.commit()
            await session.refresh(reunion)
            return reunion

    async def obtener_por_id(self, reunion_id: str) -> Reunion | None:
        """Obtiene una reunión por su clave primaria."""
        async with self._session_factory() as session:
            return await session.get(Reunion, reunion_id)

    async def actualizar_estado(
        self, reunion_id: str, estado: str, causa_fallo: str | None = None
    ) -> None:
        """Actualiza el estado_proceso y opcionalmente la causa_fallo de una reunión."""
        async with self._session_factory() as session:
            stmt = (
                update(Reunion)
                .where(Reunion.id == reunion_id)
                .values(estado_proceso=estado, causa_fallo=causa_fallo)
            )
            await session.execute(stmt)
            await session.commit()
