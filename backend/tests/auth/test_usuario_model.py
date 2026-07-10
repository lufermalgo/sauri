"""Modelo Usuario y su migración Alembic (chrome-side-panel, Tarea 13.7).

Validates: Requirements 13.1, 13.2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Usuario


@pytest.mark.asyncio
async def test_usuario_se_puede_crear_y_leer(db_session: AsyncSession):
    usuario = Usuario(
        id=str(uuid.uuid4()),
        email="comercial@summan.com",
        nombre="Comercial Uno",
        password_hash="$2b$12$hashfalsoparapruebas",
        es_comercial=True,
        creado_en=datetime.now(timezone.utc),
    )
    db_session.add(usuario)
    await db_session.commit()

    recuperado = await db_session.get(Usuario, usuario.id)
    assert recuperado is not None
    assert recuperado.email == "comercial@summan.com"
    assert recuperado.es_comercial is True


@pytest.mark.asyncio
async def test_usuario_email_es_unico(db_session: AsyncSession):
    email = "duplicado@summan.com"
    db_session.add(
        Usuario(
            id=str(uuid.uuid4()),
            email=email,
            nombre="Uno",
            password_hash="hash1",
            es_comercial=True,
            creado_en=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    db_session.add(
        Usuario(
            id=str(uuid.uuid4()),
            email=email,
            nombre="Dos",
            password_hash="hash2",
            es_comercial=True,
            creado_en=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
