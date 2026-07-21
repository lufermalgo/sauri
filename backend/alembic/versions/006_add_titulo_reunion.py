"""Add titulo column to reuniones.

Permite que las notas muestren el título/nombre real de la reunión (capturado
por el content script de la extensión) en vez de un placeholder genérico.

Revision ID: 006_add_titulo_reunion
Revises: 005_fix_uuid_columns
Create Date: 2026-07-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_titulo_reunion"
down_revision: Union[str, None] = "005_fix_uuid_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reuniones", sa.Column("titulo", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("reuniones", "titulo")
