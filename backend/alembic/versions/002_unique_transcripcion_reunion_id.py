"""Add unique constraint on transcripciones.reunion_id.

Revision ID: 002_unique_transcripcion_reunion_id
Revises: 001_initial_schema
Create Date: 2024-01-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_uq_transcripcion"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_transcripcion_reunion_id",
        "transcripciones",
        ["reunion_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_transcripcion_reunion_id",
        "transcripciones",
        type_="unique",
    )
