"""A table per node (option C, owner 10 Nov 2026): locate_items, frames, verify_findings, verify_vehicle,
confirmed_cars, photo_results, plan_queries, prices. node_results keeps the exact JSON.

Revision ID: 0004_node_tables
Revises: 0003_knowledge
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0004_node_tables"
down_revision = "0003_knowledge"
branch_labels = None
depends_on = None


def _run(primary: bool = True) -> sa.Column:
    return sa.Column("run_id", sa.Text, sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=primary,
                     nullable=False)


def _item_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["run_id", "item_id"], ["locate_items.run_id", "locate_items.item_id"],
                                   ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "locate_items", _run(),
        sa.Column("item_id", sa.Text, primary_key=True),
        sa.Column("category", sa.Text), sa.Column("label", sa.Text), sa.Column("side", sa.Text),
        sa.Column("t", sa.Float), sa.Column("t_text", sa.Text),
    )
    op.create_table(
        "frames",
        sa.Column("run_id", sa.Text, primary_key=True), sa.Column("item_id", sa.Text, primary_key=True),
        sa.Column("file", sa.Text), sa.Column("t", sa.Float), sa.Column("sharpness", sa.Float),
        sa.Column("frames_scored", sa.Integer), sa.Column("skipped", sa.Text),
        _item_fk(),
    )
    op.create_table(
        "verify_findings",
        sa.Column("run_id", sa.Text, primary_key=True), sa.Column("item_id", sa.Text, primary_key=True),
        sa.Column("confirmed", sa.Boolean), sa.Column("part", sa.Text), sa.Column("issue", sa.Text),
        sa.Column("severity", sa.Text), sa.Column("action", sa.Text), sa.Column("description", sa.Text),
        sa.Column("reason", sa.Text), sa.Column("tyre_position", sa.Text), sa.Column("tyre_score", sa.Integer),
        sa.Column("tread", sa.Text), sa.Column("best_frame", sa.Text),
        _item_fk(),
    )
    op.create_table(
        "verify_vehicle", _run(),
        sa.Column("make", sa.Text), sa.Column("model", sa.Text), sa.Column("variant", sa.Text),
        sa.Column("year", sa.Integer), sa.Column("fuel", sa.Text), sa.Column("plate", sa.Text),
        sa.Column("plate_source", sa.Text), sa.Column("plate_confidence", sa.Float), sa.Column("badge", sa.Text),
        sa.Column("odometer_km", sa.Integer), sa.Column("answered_by", sa.Text),
    )
    op.create_table(
        "confirmed_cars", _run(),
        sa.Column("make", sa.Text), sa.Column("model", sa.Text), sa.Column("variant", sa.Text),
        sa.Column("year", sa.Integer), sa.Column("fuel", sa.Text), sa.Column("plate", sa.Text),
        sa.Column("city", sa.Text), sa.Column("state", sa.Text), sa.Column("odometer_km", sa.Integer),
        sa.Column("changed", ARRAY(sa.Text)), sa.Column("skipped", ARRAY(sa.Text)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "photo_results", _run(),
        sa.Column("slot", sa.Text, primary_key=True), sa.Column("file", sa.Text),
        sa.Column("tyre_score", sa.Integer), sa.Column("tread", sa.Text), sa.Column("odometer_km", sa.Integer),
        sa.Column("confidence", sa.Float), sa.Column("used", sa.Boolean),
    )
    op.create_table(
        "plan_queries",
        sa.Column("id", sa.BigInteger, primary_key=True), _run(primary=False),
        sa.Column("kind", sa.Text, nullable=False), sa.Column("for_item", sa.Text), sa.Column("tier", sa.Text),
        sa.Column("query", sa.Text, nullable=False),
    )
    op.create_index("ix_plan_queries_run", "plan_queries", ["run_id"])
    op.create_table(
        "prices", _run(),
        sa.Column("status", sa.Text), sa.Column("low_inr", sa.Integer), sa.Column("high_inr", sa.Integer),
        sa.Column("new_price_inr", sa.Integer), sa.Column("variant_match", sa.Text),
        sa.Column("car_age_years", sa.Integer), sa.Column("listings_used", sa.Integer),
        sa.Column("repairs_total_inr", sa.Integer), sa.Column("reason", sa.Text),
    )


def downgrade() -> None:
    for t in ("prices", "plan_queries", "photo_results", "confirmed_cars", "verify_vehicle", "verify_findings",
              "frames", "locate_items"):
        op.drop_table(t)
