"""Admin app: audit log, config and prompt versions, runs pinned to versions (platform step 6, docs/platform/06-admin.md §5).

Revision ID: 0006_admin
Revises: 0005_users
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_admin"
down_revision = "0005_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("admin_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text, nullable=False, index=True),
        sa.Column("target", sa.Text),
        sa.Column("details", JSONB),
    )
    op.create_table(
        "config_versions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text),
        sa.Column("data", JSONB, nullable=False),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text),
        sa.Column("text", sa.Text, nullable=False),
    )
    op.add_column("runs", sa.Column("config_version_id", sa.BigInteger, sa.ForeignKey("config_versions.id")))
    op.add_column("runs", sa.Column("prompt_version_ids", JSONB))


def downgrade() -> None:
    op.drop_column("runs", "prompt_version_ids")
    op.drop_column("runs", "config_version_id")
    op.drop_table("prompt_versions")
    op.drop_table("config_versions")
    op.drop_table("audit_log")
