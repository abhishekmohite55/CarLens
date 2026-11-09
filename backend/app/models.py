"""Database tables (platform step 2, docs/platform/02-database-design.md §4).

The migrations in backend/alembic/versions/ create these tables; this file describes them to SQLAlchemy.
Change both together.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --- RTO (replaces rto_codes.csv) ---

class State(Base):
    __tablename__ = "states"
    code: Mapped[str] = mapped_column(Text, primary_key=True)  # MH
    name: Mapped[str] = mapped_column(Text)  # Maharashtra


class RtoCode(Base):
    __tablename__ = "rto_codes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state_code: Mapped[str] = mapped_column(Text, ForeignKey("states.code"))
    number: Mapped[str] = mapped_column(Text)  # as written in the csv: "14", "08AA"; one number can have several cities (LA 1, LA 2)
    city: Mapped[str] = mapped_column(Text)
    statewide: Mapped[bool] = mapped_column(Boolean, default=False)  # "Statewide (current series)" rows
    __table_args__ = (Index("ix_rto_codes_state_number", "state_code", "number"),)


# --- Layer 1: index ---

class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    video_sha256: Mapped[str | None] = mapped_column(Text, index=True)
    original_filename: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, default="uploaded")  # uploaded / running / awaiting_confirm / complete / failed
    failed_at: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    git_commit: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class NodeRun(Base):
    __tablename__ = "node_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("runs.id", ondelete="CASCADE"))
    node: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # running / done / failed / skipped
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_node_runs_run_node", "run_id", "node"),)


# --- Layer 2: node outputs (today's JSON files) ---

class NodeResult(Base):
    __tablename__ = "node_results"
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    node: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)  # file name: response.json, manifest.json, ...
    data: Mapped[Any] = mapped_column(JSONB)
    saved_at: Mapped[datetime] = _now()


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # No foreign key yet: events are recorded from stage 2.0, runs rows only exist from stage 2.1.
    run_id: Mapped[str] = mapped_column(Text, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    node: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)


# --- Layer 3: reusable knowledge ---

class SearchResult(Base):
    __tablename__ = "search_results"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)  # listing / new_price / part / tyre
    for_item: Mapped[str | None] = mapped_column(Text)  # part name or tyre id
    query: Mapped[str | None] = mapped_column(Text)  # reference only, lookups never match on it
    make_key: Mapped[str | None] = mapped_column(Text)
    model_key: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    first_run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("runs.id", ondelete="SET NULL"))
    # Unique (url, md5(snippet)) is an expression index, created in migration 0003.


class PriceFigure(Base):
    __tablename__ = "price_figures"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    figure_group: Mapped[str] = mapped_column(Text)  # listing / new_price / part / tyre ("group" is reserved in SQL)
    type: Mapped[str | None] = mapped_column(Text)
    price_low_inr: Mapped[int] = mapped_column(Integer)
    price_high_inr: Mapped[int] = mapped_column(Integer)
    price_text: Mapped[str | None] = mapped_column(Text)
    make_key: Mapped[str | None] = mapped_column(Text)
    model_key: Mapped[str | None] = mapped_column(Text)
    variant_key: Mapped[str | None] = mapped_column(Text)
    make: Mapped[str | None] = mapped_column(Text)
    model_as_written: Mapped[str | None] = mapped_column(Text)
    variant_as_written: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    km: Mapped[int | None] = mapped_column(Integer)
    fuel: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    part: Mapped[str | None] = mapped_column(Text)
    tyre_size: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    first_run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("runs.id", ondelete="SET NULL"))
    __table_args__ = (
        UniqueConstraint("source_url", "figure_group", "price_low_inr", "price_high_inr", "model_key", "year",
                         name="uq_price_figures_listing", postgresql_nulls_not_distinct=True),
        Index("ix_price_figures_car", "model_key", "year"),
    )
