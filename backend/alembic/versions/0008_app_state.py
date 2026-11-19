"""App state: maintenance mode during a deploy (platform step 9, docs/platform/09-cd.md §5a).

Revision ID: 0008_app_state
Revises: 0007_role_user
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_app_state"
down_revision = "0007_role_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_state",
        sa.Column("id", sa.Integer, primary_key=True),  # always 1: one row for the whole app
        sa.Column("maintenance", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("maintenance_since", sa.DateTime(timezone=True)),
        sa.Column("maintenance_by", sa.Text),  # "deploy <tag>" or who switched it
    )
    op.execute("INSERT INTO app_state (id, maintenance) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("app_state")
