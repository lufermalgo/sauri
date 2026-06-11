"""Repositorio de persistencia para la entidad GrabacionDeSesion."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import GrabacionDeSesion


class GrabacionRepository:
    """Repositorio SQLAlchemy para GrabacionDeSesion — metadatos y refs a blobs en AlmacenDeObjetos."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def crear(self, grabacion: GrabacionDeSesion) -> GrabacionDeSesion:
        """Persiste una nueva grabación de sesión."""
        async with self._session_factory() as session:
            session.add(grabacion)
            await session.commit()
            await session.refresh(grabacion)
            return grabacion

    async def obtener_por_reunion(self, reunion_id: str) -> GrabacionDeSesion | None:
        """Obtiene la grabación asociada a una reunión."""
        async with self._session_factory() as session:
            stmt = select(GrabacionDeSesion).where(GrabacionDeSesion.reunion_id == reunion_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def existe_por_clave_idempotencia(self, clave: str) -> bool:
        """Verifica si ya existe una grabación con la clave de idempotencia dada."""
        async with self._session_factory() as session:
            stmt = select(GrabacionDeSesion.id).where(
                GrabacionDeSesion.clave_idempotencia == clave
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
