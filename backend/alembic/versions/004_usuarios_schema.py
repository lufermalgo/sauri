"""Usuarios schema: almacén mínimo de usuarios comerciales autorizados.

Revision ID: 004_usuarios_schema
Revises: 003_diarizacion_schema
Create Date: 2026-07-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_usuarios_schema"
down_revision: str | None = "003_diarizacion_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("nombre", sa.String(256), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("es_comercial", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_usuario_email"),
    )


def downgrade() -> None:
    op.drop_table("usuarios")
