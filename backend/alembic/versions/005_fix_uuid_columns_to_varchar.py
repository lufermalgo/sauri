"""Fix id/FK columns from native Postgres UUID to VARCHAR(36).

Every ORM model maps its ids as `Mapped[str] = mapped_column(String(36), ...)`
(domain convention: ids are generated with `str(uuid.uuid4())`), but migrations
001 and 003 created the underlying columns as native `UUID(as_uuid=True)`. Under
asyncpg, SQLAlchemy binds these str-typed parameters with an explicit `::VARCHAR`
cast, which Postgres rejects against a `uuid` column
(`DatatypeMismatchError: column "id" is of type uuid but expression is of type
character varying`) — breaking every insert/filter on these tables. Only ever
caught now because the test suite runs against in-memory SQLite, which doesn't
distinguish the two types.

Foreign keys must be dropped before their columns (or the column they point to)
can change type, then recreated afterwards.

Revision ID: 005_fix_uuid_columns
Revises: 004_usuarios_schema
Create Date: 2026-07-21 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_fix_uuid_columns"
down_revision: str | None = "004_usuarios_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS = [
    # (constraint_name, table, column, referenced_table, referenced_column, ondelete)
    ("estado_historial_reunion_id_fkey", "estado_historial", "reunion_id", "reuniones", "id", "CASCADE"),
    ("grabaciones_de_sesion_reunion_id_fkey", "grabaciones_de_sesion", "reunion_id", "reuniones", "id", "CASCADE"),
    ("transcripciones_reunion_id_fkey", "transcripciones", "reunion_id", "reuniones", "id", "CASCADE"),
    (
        "turnos_de_habla_transcripcion_id_fkey",
        "turnos_de_habla",
        "transcripcion_id",
        "transcripciones",
        "id",
        "CASCADE",
    ),
    (
        "notificaciones_de_grabacion_reunion_id_fkey",
        "notificaciones_de_grabacion",
        "reunion_id",
        "reuniones",
        "id",
        "CASCADE",
    ),
    ("diarizaciones_reunion_id_fkey", "diarizaciones", "reunion_id", "reuniones", "id", None),
    ("diarizaciones_transcripcion_id_fkey", "diarizaciones", "transcripcion_id", "transcripciones", "id", None),
    ("hablantes_diarizacion_id_fkey", "hablantes", "diarizacion_id", "diarizaciones", "id", "CASCADE"),
    (
        "asignaciones_de_hablante_diarizacion_id_fkey",
        "asignaciones_de_hablante",
        "diarizacion_id",
        "diarizaciones",
        "id",
        "CASCADE",
    ),
    ("asignaciones_de_hablante_turno_id_fkey", "asignaciones_de_hablante", "turno_id", "turnos_de_habla", "id", None),
    (
        "asignaciones_de_hablante_hablante_id_fkey",
        "asignaciones_de_hablante",
        "hablante_id",
        "hablantes",
        "id",
        "CASCADE",
    ),
]

_COLUMNAS_UUID = [
    ("reuniones", "id"),
    ("reuniones", "creada_por"),
    ("estado_historial", "id"),
    ("estado_historial", "reunion_id"),
    ("grabaciones_de_sesion", "id"),
    ("grabaciones_de_sesion", "reunion_id"),
    ("transcripciones", "id"),
    ("transcripciones", "reunion_id"),
    ("turnos_de_habla", "id"),
    ("turnos_de_habla", "transcripcion_id"),
    ("notificaciones_de_grabacion", "id"),
    ("notificaciones_de_grabacion", "reunion_id"),
    ("registro_de_acceso", "id"),
    ("registro_de_acceso", "usuario_id"),
    ("diarizaciones", "id"),
    ("diarizaciones", "reunion_id"),
    ("diarizaciones", "transcripcion_id"),
    ("hablantes", "id"),
    ("hablantes", "diarizacion_id"),
    ("asignaciones_de_hablante", "id"),
    ("asignaciones_de_hablante", "diarizacion_id"),
    ("asignaciones_de_hablante", "turno_id"),
    ("asignaciones_de_hablante", "hablante_id"),
]


def upgrade() -> None:
    for constraint, table, *_ in _FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")

    for tabla, columna in _COLUMNAS_UUID:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE VARCHAR(36) USING {columna}::text")

    for constraint, table, column, ref_table, ref_column, ondelete in _FOREIGN_KEYS:
        op.create_foreign_key(constraint, table, ref_table, [column], [ref_column], ondelete=ondelete)


def downgrade() -> None:
    for constraint, table, *_ in _FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")

    for tabla, columna in reversed(_COLUMNAS_UUID):
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE UUID USING {columna}::uuid")

    for constraint, table, column, ref_table, ref_column, ondelete in _FOREIGN_KEYS:
        op.create_foreign_key(constraint, table, ref_table, [column], [ref_column], ondelete=ondelete)
