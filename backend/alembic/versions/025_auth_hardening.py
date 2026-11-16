"""Login rate limiting counters and per-user session revocation (#1069)."""

import sqlalchemy as sa

from alembic import op

revision = "025_auth_hardening"
down_revision = "024_regeneration_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "login_attempts",
        sa.Column("scope", sa.String(16), primary_key=True),
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_column("users", "token_version")
