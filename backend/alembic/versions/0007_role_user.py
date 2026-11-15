"""Role "tester" renamed to "user": the app is the production app (rename stage, docs/platform/rename-app.md §3.1).

Revision ID: 0007_role_user
Revises: 0006_admin
Create Date: 2026-11-15
"""
from alembic import op

revision = "0007_role_user"
down_revision = "0006_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'user' WHERE role = 'tester'")
    op.alter_column("users", "role", server_default="user")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'tester' WHERE role = 'user'")
    op.alter_column("users", "role", server_default="tester")
