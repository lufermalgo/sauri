"""Dependencias FastAPI para autenticación JWT."""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.auth.schemas import UsuarioAutenticado
from app.auth.token import JWT_ALGORITHM, JWT_SECRET

_bearer_scheme = HTTPBearer(auto_error=False)

# TODO(auth): Implementar flujo de login real en la extensión y eliminar
# esta variable de bypass. Ticket pendiente: autenticación extensión → backend.
_AUTH_DISABLED = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")

_DEV_USER = UsuarioAutenticado(
    id="dev-user-00000000",
    email="dev@sauri.local",
    nombre="Developer (auth disabled)",
    es_comercial=True,
)


async def obtener_usuario_actual(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UsuarioAutenticado:
    """Extrae y valida el token JWT del header Authorization.

    Returns:
        UsuarioAutenticado con los datos del token.

    Raises:
        HTTPException 401: si el token falta, es inválido o está expirado.
    """
    # Bypass auth for local development (AUTH_DISABLED=1 in env)
    if _AUTH_DISABLED:
        return _DEV_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub: str | None = payload.get("sub")
    email: str | None = payload.get("email")
    nombre: str | None = payload.get("nombre")
    es_comercial: bool | None = payload.get("es_comercial")

    if sub is None or email is None or nombre is None or es_comercial is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token con claims incompletos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UsuarioAutenticado(
        id=sub,
        email=email,
        nombre=nombre,
        es_comercial=es_comercial,
    )
