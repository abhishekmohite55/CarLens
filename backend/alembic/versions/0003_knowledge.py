"""Reusable knowledge: search_results (Tavily) and price_figures (extracted prices), by car with dates.

Revision ID: 0003_knowledge
Revises: 0002_runs
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_knowledge"
down_revision = "0002_runs"
branch_labels = None
depends_on = None


def _seen() -> list[sa.Column]:
    return [
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("first_run_id", sa.Text, sa.ForeignKey("runs.id", ondelete="SET NULL")),
    ]


def upgrade() -> None:
    op.create_table(
        "search_results",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("snippet", sa.Text, nullable=False),
        sa.Column("kind", sa.Text),
        sa.Column("for_item", sa.Text),
        sa.Column("query", sa.Text),
        sa.Column("make_key", sa.Text),
        sa.Column("model_key", sa.Text),
        sa.Column("year", sa.Integer),
        *_seen(),
    )
    # Snippets can be long, so the unique key uses their md5 instead of the full text.
    op.execute("CREATE UNIQUE INDEX uq_search_results_url_snippet ON search_results (url, md5(snippet))")
    op.create_index("ix_search_results_car", "search_results", ["model_key", "year"])

    op.create_table(
        "price_figures",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("figure_group", sa.Text, nullable=False),
        sa.Column("type", sa.Text),
        sa.Column("price_low_inr", sa.Integer, nullable=False),
        sa.Column("price_high_inr", sa.Integer, nullable=False),
        sa.Column("price_text", sa.Text),
        sa.Column("make_key", sa.Text),
        sa.Column("model_key", sa.Text),
        sa.Column("variant_key", sa.Text),
        sa.Column("make", sa.Text),
        sa.Column("model_as_written", sa.Text),
        sa.Column("variant_as_written", sa.Text),
        sa.Column("year", sa.Integer),
        sa.Column("km", sa.Integer),
        sa.Column("fuel", sa.Text),
        sa.Column("state", sa.Text),
        sa.Column("city", sa.Text),
        sa.Column("part", sa.Text),
        sa.Column("tyre_size", sa.Text),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_title", sa.Text),
        *_seen(),
        sa.UniqueConstraint("source_url", "figure_group", "price_low_inr", "price_high_inr", "model_key", "year",
                            name="uq_price_figures_listing", postgresql_nulls_not_distinct=True),
    )
    op.create_index("ix_price_figures_car", "price_figures", ["model_key", "year"])


def downgrade() -> None:
    op.drop_table("price_figures")
    op.drop_table("search_results")
