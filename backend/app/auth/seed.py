"""Semilla mínima y determinista de Usuarios comerciales autorizados.

NO es una integración con el IdP de Summan: es un almacén mínimo que
respalda el Servicio_De_Autenticacion mientras esa integración no exista
(Req. 13.1, 13.2, 13.3). La contraseña por defecto se puede sobrescribir
vía la variable de entorno SAURI_SEED_PASSWORD (solo para desarrollo/test).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.infra.models import Usuario

_PASSWORD_SEMILLA_DEFECTO = "sauri-dev-2026"


def _password_semilla() -> str:
    return os.getenv("SAURI_SEED_PASSWORD", _PASSWORD_SEMILLA_DEFECTO)


USUARIOS_SEMILLA: list[dict[str, str | bool]] = [
    {
        "email": "comercial1@summan.com",
        "nombre": "Comercial Summan Uno",
        "es_comercial": True,
    },
    {
        "email": "comercial2@summan.com",
        "nombre": "Comercial Summan Dos",
        "es_comercial": True,
    },
]


async def sembrar_usuarios(session: AsyncSession) -> list[Usuario]:
    """Inserta la semilla mínima de usuarios si aún no existen (idempotente)."""
    creados: list[Usuario] = []
    password = _password_semilla()
    for datos in USUARIOS_SEMILLA:
        stmt = select(Usuario).where(Usuario.email == datos["email"])
        existente = (await session.execute(stmt)).scalar_one_or_none()
        if existente is not None:
            continue
        usuario = Usuario(
            id=str(uuid.uuid4()),
            email=str(datos["email"]),
            nombre=str(datos["nombre"]),
            password_hash=hash_password(password),
            es_comercial=bool(datos["es_comercial"]),
            creado_en=datetime.now(UTC),
        )
        session.add(usuario)
        creados.append(usuario)
    return creados
