"""Run tables: runs, node_runs, node_results, run_events.

Revision ID: 0002_runs
Revises: 0001_rto
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_runs"
down_revision = "0001_rto"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("video_sha256", sa.Text),
        sa.Column("original_filename", sa.Text),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("duration_sec", sa.Float),
        sa.Column("status", sa.Text, nullable=False, server_default="uploaded"),
        sa.Column("failed_at", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("git_commit", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_runs_video_sha256", "runs", ["video_sha256"])

    op.create_table(
        "node_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        _ts("started_at"),
        _ts("finished_at", nullable=True),
        sa.Column("summary", sa.Text),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_node_runs_run_node", "node_runs", ["run_id", "node"])

    op.create_table(
        "node_results",
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("data", JSONB),
        _ts("saved_at"),
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),  # FK added in stage 2.1
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("data", JSONB),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("node_results")
    op.drop_table("node_runs")
    op.drop_table("runs")
