"""VIN lookups (stage U1, docs/backend/07-us-market.md §4.3): one row per provider call, reused for the same VIN.

Revision ID: 0010_vin_lookups
Revises: 0009_market
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_vin_lookups"
down_revision = "0009_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vin_lookups",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("vin", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text),
        sa.Column("car", JSONB),
        sa.Column("raw", JSONB),
        sa.Column("ms", sa.Integer),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vin_lookups_vin_provider", "vin_lookups", ["vin", "provider"])
    op.create_index("ix_vin_lookups_user_id", "vin_lookups", ["user_id"])


def downgrade() -> None:
    op.drop_table("vin_lookups")
