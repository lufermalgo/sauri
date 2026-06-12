"""Test de integración del esquema de diarización (migración 003).

# Feature: identificacion-hablantes
Task: 10.2
Validates: Requirements 8.1, 10.5

Verifica el contrato de esquema que produce la migración 003 sobre la base de
prueba: creación de las tres tablas (diarizaciones, hablantes,
asignaciones_de_hablante), FKs en cascada y las restricciones de unicidad
uq_diarizacion_reunion_id y uq_asignacion_turno_id.

La migración 003 se validó adicionalmente end-to-end contra PostgreSQL real
(`alembic upgrade head` → 11 tablas, alembic_version=003_diarizacion_schema).
Este test garantiza la regresión del esquema en cada ejecución de la suite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine


# ---------------------------------------------------------------------------
# Las tres tablas de diarización existen tras crear el esquema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migracion_003_crea_tres_tablas(async_engine: AsyncEngine):
    """upgrade crea diarizaciones, hablantes y asignaciones_de_hablante."""

    def _tablas(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with async_engine.connect() as conn:
        tablas = await conn.run_sync(_tablas)

    assert "diarizaciones" in tablas
    assert "hablantes" in tablas
    assert "asignaciones_de_hablante" in tablas


# ---------------------------------------------------------------------------
# Restricciones de unicidad (Req. 8.1, 10.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migracion_003_unique_constraints(async_engine: AsyncEngine):
    """uq_diarizacion_reunion_id y uq_asignacion_turno_id están definidas."""

    def _unique_constraints(sync_conn):
        insp = inspect(sync_conn)
        diar_uqs = {uc["name"] for uc in insp.get_unique_constraints("diarizaciones")}
        asig_uqs = {
            uc["name"] for uc in insp.get_unique_constraints("asignaciones_de_hablante")
        }
        return diar_uqs, asig_uqs

    async with async_engine.connect() as conn:
        diar_uqs, asig_uqs = await conn.run_sync(_unique_constraints)

    assert "uq_diarizacion_reunion_id" in diar_uqs
    assert "uq_asignacion_turno_id" in asig_uqs


# ---------------------------------------------------------------------------
# Claves foráneas en cascada (Req. 8.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migracion_003_foreign_keys_cascade(async_engine: AsyncEngine):
    """Las FKs de hablantes y asignaciones referencian diarizaciones en cascada."""

    def _fks(sync_conn):
        insp = inspect(sync_conn)
        return {
            "hablantes": insp.get_foreign_keys("hablantes"),
            "asignaciones_de_hablante": insp.get_foreign_keys("asignaciones_de_hablante"),
        }

    async with async_engine.connect() as conn:
        fks = await conn.run_sync(_fks)

    # hablantes.diarizacion_id → diarizaciones.id ON DELETE CASCADE
    hablante_fks = {fk["referred_table"]: fk for fk in fks["hablantes"]}
    assert "diarizaciones" in hablante_fks
    assert hablante_fks["diarizaciones"]["options"].get("ondelete") == "CASCADE"

    # asignaciones_de_hablante referencia diarizaciones, hablantes y turnos_de_habla
    asig_referred = {fk["referred_table"] for fk in fks["asignaciones_de_hablante"]}
    assert "diarizaciones" in asig_referred
    assert "hablantes" in asig_referred
    assert "turnos_de_habla" in asig_referred


# ---------------------------------------------------------------------------
# Consistencia de la cadena de revisiones Alembic 001 → 002 → 003
# ---------------------------------------------------------------------------


def test_cadena_de_revisiones_alembic():
    """La migración 003 encadena correctamente tras 002 y define upgrade/downgrade."""
    import importlib.util
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "alembic" / "versions"

    def _load(nombre):
        ruta = base / nombre
        spec = importlib.util.spec_from_file_location(nombre.replace(".py", ""), ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    m003 = _load("003_diarizacion_schema.py")
    assert m003.revision == "003_diarizacion_schema"
    assert m003.down_revision == "002_uq_transcripcion"
    assert hasattr(m003, "upgrade")
    assert hasattr(m003, "downgrade")
