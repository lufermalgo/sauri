"""Diarización schema: diarizaciones, hablantes, asignaciones_de_hablante.

Revision ID: 003_diarizacion_schema
Revises: 002_unique_transcripcion_reunion_id
Create Date: 2026-06-12 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "003_diarizacion_schema"
down_revision: Union[str, None] = "002_uq_transcripcion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Table: diarizaciones ---
    op.create_table(
        "diarizaciones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reunion_id", UUID(as_uuid=True),
            sa.ForeignKey("reuniones.id"), nullable=False,
        ),
        sa.Column(
            "transcripcion_id", UUID(as_uuid=True),
            sa.ForeignKey("transcripciones.id"), nullable=False,
        ),
        sa.Column("proveedor", sa.String(128), nullable=False),
        sa.Column("num_hablantes", sa.Integer, nullable=False),
        sa.Column("estado_diarizacion", sa.String(32), nullable=False),
        sa.Column("causa_fallo", sa.String(64), nullable=True),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("reunion_id", name="uq_diarizacion_reunion_id"),
    )

    # --- Table: hablantes ---
    op.create_table(
        "hablantes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "diarizacion_id", UUID(as_uuid=True),
            sa.ForeignKey("diarizaciones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("etiqueta_cruda", sa.String(128), nullable=False),
        sa.Column("etiqueta", sa.String(64), nullable=False),
        sa.Column("orden", sa.Integer, nullable=False),
    )

    # --- Table: asignaciones_de_hablante ---
    op.create_table(
        "asignaciones_de_hablante",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "diarizacion_id", UUID(as_uuid=True),
            sa.ForeignKey("diarizaciones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "turno_id", UUID(as_uuid=True),
            sa.ForeignKey("turnos_de_habla.id"), nullable=False,
        ),
        sa.Column(
            "hablante_id", UUID(as_uuid=True),
            sa.ForeignKey("hablantes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.UniqueConstraint("turno_id", name="uq_asignacion_turno_id"),
    )


def downgrade() -> None:
    op.drop_table("asignaciones_de_hablante")
    op.drop_table("hablantes")
    op.drop_table("diarizaciones")
