"""Autorización y auditoría de denegaciones."""

from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import registrar_acceso
from app.auth.dependencies import obtener_usuario_actual
from app.auth.schemas import UsuarioAutenticado


def verificar_autorizacion(usuario: UsuarioAutenticado, recurso: str, accion: str) -> bool:
    """Verifica si el usuario está autorizado para la acción sobre el recurso.

    Política actual: solo usuarios con es_comercial=True tienen acceso.

    Args:
        usuario: Usuario autenticado.
        recurso: Recurso al que se intenta acceder.
        accion: Acción que se intenta realizar.

    Returns:
        True si autorizado, False si denegado.
    """
    return usuario.es_comercial


def requerir_comercial(
    get_session: Callable[..., Any],
) -> Any:
    """Crea una dependencia FastAPI que requiere usuario comercial autorizado.

    Args:
        get_session: Callable que provee la AsyncSession de SQLAlchemy (dependencia de DB).

    Returns:
        Dependencia FastAPI que retorna UsuarioAutenticado si autorizado.
    """

    async def _dependency(
        request: Request,
        usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
        session: AsyncSession = Depends(get_session),
    ) -> UsuarioAutenticado:
        recurso = f"{request.method} {request.url.path}"

        if not verificar_autorizacion(usuario, recurso, request.method):
            await registrar_acceso(
                session=session,
                usuario_id=usuario.id,
                recurso=recurso,
                resultado="denegado",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso restringido a usuarios comerciales autorizados",
            )

        return usuario

    return _dependency
