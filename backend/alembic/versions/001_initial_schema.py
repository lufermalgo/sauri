"""Initial schema for meeting-capture-transcription module.

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Table: reuniones ---
    op.create_table(
        "reuniones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("enlace_meet", sa.String(512), nullable=False),
        sa.Column("origen", sa.String(64), nullable=False),
        sa.Column("id_invitacion_calendario", sa.String(256), nullable=True),
        sa.Column("hora_inicio_programada", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado_proceso", sa.String(64), nullable=False),
        sa.Column("causa_fallo", sa.String(64), nullable=True),
        sa.Column("creada_por", UUID(as_uuid=True), nullable=False),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- Table: estado_historial ---
    op.create_table(
        "estado_historial",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reunion_id", UUID(as_uuid=True),
            sa.ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("estado", sa.String(64), nullable=False),
        sa.Column("causa_fallo", sa.String(64), nullable=True),
        sa.Column("ocurrido_en", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Table: grabaciones_de_sesion ---
    op.create_table(
        "grabaciones_de_sesion",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reunion_id", UUID(as_uuid=True),
            sa.ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("clave_idempotencia", sa.String(256), nullable=False),
        sa.Column("origen_captura", sa.String(64), nullable=False),
        sa.Column("audio_ref", sa.String(1024), nullable=False),
        sa.Column("video_ref", sa.String(1024), nullable=True),
        sa.Column("duracion_segundos", sa.Integer, nullable=False),
        sa.Column("interrumpida", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizada_en", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reunion_id", name="uq_grabacion_reunion_id"),
        sa.UniqueConstraint("clave_idempotencia", name="uq_grabacion_clave_idempotencia"),
    )

    # --- Table: transcripciones ---
    op.create_table(
        "transcripciones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reunion_id", UUID(as_uuid=True),
            sa.ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("idioma", sa.String(16), nullable=False, server_default="es-CO"),
        sa.Column("proveedor", sa.String(128), nullable=False),
        sa.Column("soporta_turnos", sa.Boolean, nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- Table: turnos_de_habla ---
    op.create_table(
        "turnos_de_habla",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transcripcion_id", UUID(as_uuid=True),
            sa.ForeignKey("transcripciones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("inicio_ms", sa.Integer, nullable=False),
        sa.Column("fin_ms", sa.Integer, nullable=False),
        sa.Column("orden", sa.Integer, nullable=False),
    )

    # --- Table: notificaciones_de_grabacion ---
    op.create_table(
        "notificaciones_de_grabacion",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reunion_id", UUID(as_uuid=True),
            sa.ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("emitida_en", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Table: registro_de_acceso ---
    op.create_table(
        "registro_de_acceso",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("usuario_id", UUID(as_uuid=True), nullable=True),
        sa.Column("recurso", sa.String(512), nullable=False),
        sa.Column("resultado", sa.String(16), nullable=False),
        sa.Column("ocurrido_en", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("registro_de_acceso")
    op.drop_table("notificaciones_de_grabacion")
    op.drop_table("turnos_de_habla")
    op.drop_table("transcripciones")
    op.drop_table("grabaciones_de_sesion")
    op.drop_table("estado_historial")
    op.drop_table("reuniones")
