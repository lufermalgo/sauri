"""Auditoría de acceso — registra intentos permitidos y denegados."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import RegistroDeAcceso


async def registrar_acceso(
    session: AsyncSession,
    usuario_id: str | None,
    recurso: str,
    resultado: str,
) -> None:
    """Crea una entrada de RegistroDeAcceso en la base de datos.

    Args:
        session: Sesión async de SQLAlchemy.
        usuario_id: UUID del usuario solicitante (None si no autenticado).
        recurso: Recurso al que se intentó acceder.
        resultado: "permitido" o "denegado".
    """
    registro = RegistroDeAcceso(
        id=str(uuid4()),
        usuario_id=usuario_id,
        recurso=recurso,
        resultado=resultado,
        ocurrido_en=datetime.now(timezone.utc),
    )
    session.add(registro)
    await session.commit()
