"""Servicio_De_Autenticacion — POST /api/v1/auth/login (chrome-side-panel, Req. 13).

Valida las credenciales del Usuario_Comercial contra el almacén mínimo
`Usuario` y emite la Sesion_De_Usuario (JWT) con `crear_token`.
No es una integración con el IdP de Summan.

Requirements: 13.2, 13.3, 13.5
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.passwords import verify_password
from app.auth.schemas import LoginRequest, LoginResponse
from app.auth.token import crear_token
from app.infra.database import create_engine, create_session_factory
from app.infra.models import Usuario

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EXPIRES_MINUTES = 60


@router.post("/login", response_model=LoginResponse)
async def login(entrada: LoginRequest) -> LoginResponse:
    """Valida credenciales y emite un JWT (Req. 13.2, 13.3).

    401 si el email no existe o la contraseña es incorrecta — la respuesta
    no distingue entre ambos casos para no filtrar qué emails existen.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stmt = select(Usuario).where(Usuario.email == entrada.email)
            usuario = (await session.execute(stmt)).scalar_one_or_none()

            if usuario is None or not verify_password(entrada.password, usuario.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Credenciales inválidas",
                )

            token = crear_token(
                usuario_id=usuario.id,
                email=usuario.email,
                nombre=usuario.nombre,
                es_comercial=usuario.es_comercial,
                expires_minutes=_EXPIRES_MINUTES,
            )
            return LoginResponse(
                access_token=token,
                token_type="bearer",
                expires_in=_EXPIRES_MINUTES * 60,
            )
    finally:
        await engine.dispose()
