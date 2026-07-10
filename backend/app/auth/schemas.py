"""Esquemas Pydantic del módulo de autenticación."""

from pydantic import BaseModel


class UsuarioAutenticado(BaseModel):
    """Representa un usuario autenticado extraído del token JWT."""

    id: str  # UUID como string
    email: str
    nombre: str
    es_comercial: bool


class LoginRequest(BaseModel):
    """Solicitud de inicio de sesión (Req. 13.2)."""

    email: str
    password: str


class LoginResponse(BaseModel):
    """Respuesta del Servicio_De_Autenticacion con la Sesion_De_Usuario (Req. 13.3)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
