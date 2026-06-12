"""Repositorio de persistencia para Diarizacion, Hablante y AsignacionDeHablante.

Persiste el grafo completo de diarización en una única transacción (controlada
por el worker) y lo recupera por reunion_id con carga ansiosa (selectinload).

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.5, 10.6
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.infra.models import AsignacionDeHablante, Diarizacion, Hablante


class DiarizacionRepository:
    """Repositorio SQLAlchemy para Diarizacion — entidades en una transacción."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def crear(
        self,
        session: AsyncSession,
        diarizacion: Diarizacion,
        hablantes: list[Hablante],
        asignaciones: list[AsignacionDeHablante],
    ) -> Diarizacion:
        """Agrega la Diarizacion, sus Hablantes y Asignaciones a la sesión provista.

        No abre, cierra ni confirma la sesión: el llamador (worker) controla la
        transacción y decidirá cuándo hacer commit o rollback. Un fallo en
        cualquier escritura revierte todo (atomicidad, Req. 8.2, 8.3, 10.6).
        """
        session.add(diarizacion)
        for hablante in hablantes:
            session.add(hablante)
        for asignacion in asignaciones:
            session.add(asignacion)
        return diarizacion

    async def obtener_por_reunion(self, reunion_id: str) -> Diarizacion | None:
        """Obtiene la Diarizacion de una reunión junto con sus Hablantes y Asignaciones.

        Devuelve None si no existe (Req. 8.6). Carga ansiosa con selectinload
        para evitar lazy-loading fuera de sesión (Req. 8.5).
        """
        async with self._session_factory() as session:
            stmt = (
                select(Diarizacion)
                .where(Diarizacion.reunion_id == reunion_id)
                .options(
                    selectinload(Diarizacion.hablantes),
                    selectinload(Diarizacion.asignaciones),
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
