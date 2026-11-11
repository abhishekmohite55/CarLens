"""Users, sessions, sign-up attempts, runs.user_id (platform step 5, docs/platform/05-login.md §5).

Revision ID: 0005_users
Revises: 0004_node_tables
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_users"
down_revision = "0004_node_tables"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True, now: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if now else None)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text),
        sa.Column("google_sub", sa.Text, unique=True),
        sa.Column("role", sa.Text, nullable=False, server_default="tester"),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("totp_secret", sa.Text),
        sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"),
        _ts("locked_until"),
        _ts("created_at", nullable=False, now=True),
        _ts("approved_at"),
        _ts("last_login_at"),
    )
    op.create_table(
        "sessions",
        sa.Column("key_hash", sa.Text, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        _ts("created_at", nullable=False, now=True),
        _ts("expires_at", nullable=False),
    )
    op.create_table(
        "signup_attempts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ip", sa.Text, nullable=False, index=True),
        _ts("created_at", nullable=False, now=True),
    )
    op.add_column("runs", sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), index=True))


def downgrade() -> None:
    op.drop_column("runs", "user_id")
    op.drop_table("signup_attempts")
    op.drop_table("sessions")
    op.drop_table("users")
