"""Database tables (platform step 2, docs/platform/02-database-design.md §4).

The migrations in backend/alembic/versions/ create these tables; this file describes them to SQLAlchemy.
Change both together.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)  # step 5; NULL before
    config_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("config_versions.id"))  # step 6.3
    prompt_version_ids: Mapped[Any | None] = mapped_column(JSONB)  # step 6.3: {"verify.system.md": 7, ...}
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
    # Same expression index as migration 0003, so pytest's create_all builds it too (upsert needs it).
    __table_args__ = (Index("uq_search_results_url_snippet", "url", text("md5(snippet)"), unique=True),)


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

# --- A table per node (option C, owner 10 Nov 2026): key values as rows; node_results keeps the exact JSON ---

def _run_fk(primary: bool = True) -> Mapped[str]:
    return mapped_column(Text, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=primary)


class LocateItem(Base):
    __tablename__ = "locate_items"
    run_id: Mapped[str] = _run_fk()
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)  # L1, L2, ...
    category: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    t: Mapped[float | None] = mapped_column(Float)
    t_text: Mapped[str | None] = mapped_column(Text)


def _item_fk() -> ForeignKeyConstraint:
    # Re-running locate replaces its items, so the rows that hang off them go too.
    return ForeignKeyConstraint(["run_id", "item_id"], ["locate_items.run_id", "locate_items.item_id"], ondelete="CASCADE")


class Frame(Base):
    __tablename__ = "frames"
    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    file: Mapped[str | None] = mapped_column(Text)  # sharpest JPEG in 02_frames/
    t: Mapped[float | None] = mapped_column(Float)
    sharpness: Mapped[float | None] = mapped_column(Float)
    frames_scored: Mapped[int | None] = mapped_column(Integer)
    skipped: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (_item_fk(),)


class VerifyFinding(Base):
    __tablename__ = "verify_findings"
    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    confirmed: Mapped[bool | None] = mapped_column(Boolean)
    part: Mapped[str | None] = mapped_column(Text)
    issue: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    tyre_position: Mapped[str | None] = mapped_column(Text)
    tyre_score: Mapped[int | None] = mapped_column(Integer)
    tread: Mapped[str | None] = mapped_column(Text)
    best_frame: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (_item_fk(),)


class VerifyVehicle(Base):
    __tablename__ = "verify_vehicle"
    run_id: Mapped[str] = _run_fk()
    make: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    fuel: Mapped[str | None] = mapped_column(Text)
    plate: Mapped[str | None] = mapped_column(Text)
    plate_source: Mapped[str | None] = mapped_column(Text)  # ocr / model
    plate_confidence: Mapped[float | None] = mapped_column(Float)
    badge: Mapped[str | None] = mapped_column(Text)
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    answered_by: Mapped[str | None] = mapped_column(Text)  # model that answered


class ConfirmedCar(Base):
    __tablename__ = "confirmed_cars"
    run_id: Mapped[str] = _run_fk()
    make: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    fuel: Mapped[str | None] = mapped_column(Text)
    plate: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    changed: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    skipped: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhotoResult(Base):
    __tablename__ = "photo_results"
    run_id: Mapped[str] = _run_fk()
    slot: Mapped[str] = mapped_column(Text, primary_key=True)  # front_left ... odometer
    file: Mapped[str | None] = mapped_column(Text)
    tyre_score: Mapped[int | None] = mapped_column(Integer)
    tread: Mapped[str | None] = mapped_column(Text)
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    used: Mapped[bool | None] = mapped_column(Boolean)


class PlanQuery(Base):
    __tablename__ = "plan_queries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = _run_fk(primary=False)
    kind: Mapped[str] = mapped_column(Text)  # listing / new_price / part / tyre
    for_item: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[str | None] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_plan_queries_run", "run_id"),)


class Price(Base):
    __tablename__ = "prices"
    run_id: Mapped[str] = _run_fk()
    status: Mapped[str | None] = mapped_column(Text)
    low_inr: Mapped[int | None] = mapped_column(Integer)
    high_inr: Mapped[int | None] = mapped_column(Integer)
    new_price_inr: Mapped[int | None] = mapped_column(Integer)
    variant_match: Mapped[str | None] = mapped_column(Text)
    car_age_years: Mapped[int | None] = mapped_column(Integer)
    listings_used: Mapped[int | None] = mapped_column(Integer)
    repairs_total_inr: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)


# --- Users and sessions (platform step 5, docs/platform/05-login.md §5) ---

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)  # lowercase, trimmed
    password_hash: Mapped[str | None] = mapped_column(Text)  # argon2; NULL for Google-only users
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)  # Google's id for the person (stage 5.2)
    role: Mapped[str] = mapped_column(Text, default="tester")  # admin / tester
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending / approved / rejected
    tokens: Mapped[int] = mapped_column(Integer, default=0)  # runs left (1 token = 1 run)
    totp_secret: Mapped[str | None] = mapped_column(Text)  # authenticator setup key, admin only
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    key_hash: Mapped[str] = mapped_column(Text, primary_key=True)  # sha256 of the cookie value; the value is never stored
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SignupAttempt(Base):
    __tablename__ = "signup_attempts"  # new accounts per internet address per hour (stage 5.2)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ip: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = _now()


# --- Admin app (platform step 6, docs/platform/06-admin.md §5) ---

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = _now()
    admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, index=True)  # approve_user, set_tokens, delete_run, ...
    target: Mapped[str | None] = mapped_column(Text)  # "user 12", "run r_abc..."
    details: Mapped[Any | None] = mapped_column(JSONB)


class ConfigVersion(Base):
    __tablename__ = "config_versions"  # newest row = active (stage 6.3)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSONB)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"  # newest row per name = active (stage 6.3)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
