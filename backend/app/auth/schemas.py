"""Esquemas Pydantic del módulo de autenticación."""

from pydantic import BaseModel


class UsuarioAutenticado(BaseModel):
    """Representa un usuario autenticado extraído del token JWT."""

    id: str  # UUID como string
    email: str
    nombre: str
    es_comercial: bool
