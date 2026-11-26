"""Markets: every run is India or US (stage M0, docs/backend/07-us-market.md §11).

runs.market (in / us, old rows = in), users.market (admin's pin, empty = by location), prompt_versions.market
(old rows = in). Config versions are not rewritten: old versions are converted when they are read (config.py).

Revision ID: 0009_market
Revises: 0008_app_state
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_market"
down_revision = "0008_app_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("market", sa.Text, nullable=False, server_default="in"))
    op.create_index("ix_runs_market", "runs", ["market"])
    op.add_column("users", sa.Column("market", sa.Text, nullable=True))
    op.add_column("prompt_versions", sa.Column("market", sa.Text, nullable=False, server_default="in"))
    op.create_index("ix_prompt_versions_market_name", "prompt_versions", ["market", "name"])


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_market_name", table_name="prompt_versions")
    op.drop_column("prompt_versions", "market")
    op.drop_column("users", "market")
    op.drop_index("ix_runs_market", table_name="runs")
    op.drop_column("runs", "market")
