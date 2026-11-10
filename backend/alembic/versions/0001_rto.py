"""RTO tables: states + rto_codes, filled from seed/rto_codes.csv.

Revision ID: 0001_rto
Revises:
Create Date: 2026-11-10
"""
import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0001_rto"
down_revision = None
branch_labels = None
depends_on = None

SEED = Path(__file__).parent.parent / "seed" / "rto_codes.csv"


def read_seed(path: Path) -> tuple[list[dict], list[dict]]:
    """(states, rto rows) from the csv. Every row is kept; state name per code taken from the csv."""
    states: dict[str, str] = {}
    rows: list[dict] = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = r["State-code"].strip().upper()
            city = r["city"].strip()
            states.setdefault(code, r["state"].strip())
            rows.append({"state_code": code, "number": r["City-code"].strip().upper(), "city": city,
                         "statewide": city.lower().startswith("statewide")})
    return [{"code": c, "name": n} for c, n in sorted(states.items())], rows


def upgrade() -> None:
    states = op.create_table(
        "states",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    rto = op.create_table(
        "rto_codes",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("state_code", sa.Text, sa.ForeignKey("states.code"), nullable=False),
        sa.Column("number", sa.Text, nullable=False),
        sa.Column("city", sa.Text, nullable=False),
        sa.Column("statewide", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_rto_codes_state_number", "rto_codes", ["state_code", "number"])
    state_rows, rto_rows = read_seed(SEED)
    op.bulk_insert(states, state_rows)
    op.bulk_insert(rto, rto_rows)


def downgrade() -> None:
    op.drop_table("rto_codes")
    op.drop_table("states")
