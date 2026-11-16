"""Engine providers, per-process engine choice, privacy consents and result provenance (#1087)."""

import sqlalchemy as sa

from alembic import op

revision = "026_engine_providers"
down_revision = "025_auth_hardening"
branch_labels = None
depends_on = None

CAPABILITIES = "('transcription', 'diarization', 'summary', 'chat')"
PROVENANCE_TABLES = ("transcripts", "diarizations", "meeting_summaries")


def upgrade() -> None:
    op.create_table(
        "engine_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secret_ref", sa.String(200), nullable=True),
        sa.Column("key_hint", sa.String(4), nullable=True),
        sa.Column("key_set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "label", name="uq_engine_provider_owner_label"),
        sa.UniqueConstraint("id", "owner_id", name="uq_engine_provider_id_owner"),
    )
    op.create_index("ix_engine_providers_owner", "engine_providers", ["owner_id"])

    op.create_table(
        "engine_process_settings",
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("capability", sa.String(16), primary_key=True),
        sa.Column("provider_id", sa.String(36), nullable=True),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("local_fallback", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id", "owner_id"],
            ["engine_providers.id", "engine_providers.owner_id"],
            name="fk_engine_process_settings_provider_owner",
        ),
        sa.CheckConstraint(f"capability IN {CAPABILITIES}", name="ck_engine_process_settings_capability"),
        sa.CheckConstraint("version >= 1", name="ck_engine_process_settings_version"),
        sa.CheckConstraint(
            "provider_id IS NOT NULL OR model LIKE 'local:%'", name="ck_engine_process_settings_local_model"
        ),
    )

    op.create_table(
        "engine_privacy_consents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("notice_version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id", "owner_id"],
            ["engine_providers.id", "engine_providers.owner_id"],
            ondelete="CASCADE",
            name="fk_engine_privacy_consents_provider_owner",
        ),
        sa.CheckConstraint(f"capability IN {CAPABILITIES}", name="ck_engine_privacy_consents_capability"),
        sa.CheckConstraint("notice_version >= 1", name="ck_engine_privacy_consents_notice_version"),
    )
    op.create_index(
        "uq_engine_privacy_consents_current",
        "engine_privacy_consents",
        ["owner_id", "capability", "provider_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    for table in PROVENANCE_TABLES:
        op.add_column(table, sa.Column("engine_name", sa.String(64), nullable=True))
        op.add_column(table, sa.Column("engine_model", sa.String(256), nullable=True))
        op.add_column(table, sa.Column("engine_external", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Meeting content is untouched: only the provenance columns and the engine tables go.
    for table in reversed(PROVENANCE_TABLES):
        op.drop_column(table, "engine_external")
        op.drop_column(table, "engine_model")
        op.drop_column(table, "engine_name")
    op.drop_index("uq_engine_privacy_consents_current", table_name="engine_privacy_consents")
    op.drop_table("engine_privacy_consents")
    op.drop_table("engine_process_settings")
    op.drop_index("ix_engine_providers_owner", table_name="engine_providers")
    op.drop_table("engine_providers")
