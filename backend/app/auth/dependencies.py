"""Dependencias FastAPI para autenticación JWT."""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.auth.schemas import UsuarioAutenticado
from app.auth.token import JWT_ALGORITHM, JWT_SECRET

_bearer_scheme = HTTPBearer(auto_error=False)

_DEV_USER = UsuarioAutenticado(
    id="dev-user-00000000",
    email="dev@sauri.local",
    nombre="Developer (auth disabled)",
    es_comercial=True,
)


def _bypass_activo() -> bool:
    """Determina si el bypass AUTH_DISABLED está activo.

    Restringido al entorno de test (Req. 13.1, 13.4): con la incorporación
    de `POST /api/v1/auth/login` (chrome-side-panel), el bypass de
    desarrollo se retira fuera de pruebas automatizadas; los endpoints
    exigen un JWT real emitido por el Servicio_De_Autenticacion. Se
    conserva sólo para test (`APP_ENV=test`) donde otros módulos aún lo
    usan como atajo.
    """
    auth_disabled = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
    app_env = os.getenv("APP_ENV", "").lower()
    return auth_disabled and app_env == "test"


async def obtener_usuario_actual(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UsuarioAutenticado:
    """Extrae y valida el token JWT del header Authorization.

    Returns:
        UsuarioAutenticado con los datos del token.

    Raises:
        HTTPException 401: si el token falta, es inválido o está expirado.
    """
    # Bypass sólo en entorno de test (AUTH_DISABLED=1 y APP_ENV=test), Req. 13.1, 13.4
    if _bypass_activo():
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
