"""Utilidad para crear tokens JWT (desarrollo y testing)."""

import os
from datetime import datetime, timedelta, timezone

from jose import jwt

JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-cambiar-en-produccion")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")


def crear_token(
    usuario_id: str,
    email: str,
    nombre: str,
    es_comercial: bool,
    expires_minutes: int = 60,
) -> str:
    """Crea un token JWT con los claims del usuario.

    Args:
        usuario_id: UUID del usuario como string.
        email: Email del usuario.
        nombre: Nombre del usuario.
        es_comercial: Si el usuario es comercial autorizado.
        expires_minutes: Minutos hasta expiración del token.

    Returns:
        Token JWT codificado como string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": usuario_id,
        "email": email,
        "nombre": nombre,
        "es_comercial": es_comercial,
        "exp": now + timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
