"""Admin actions and lists (platform step 6, docs/platform/06-admin.md §6.4, §6.5, §6.8).

Every change writes its audit_log row in the same transaction. Rules live here, not in the screens.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, Table, Text, cast, delete, false, func, insert, or_, select, text, update
from sqlalchemy.engine import Connection

from .auth import AuthError, hash_password
from .config import get_config
from .db import require_engine
from .models import AuditLog, Base, NodeRun, Run, RunEvent, Session, User
from .users import MIN_PASSWORD


def _audit(conn: Connection, admin_id: int, action: str, target: str, details: dict | None = None) -> None:
    conn.execute(insert(AuditLog).values(admin_id=admin_id, action=action, target=target, details=details or {}))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def new_tokens(current: int, set_to: int | None, add: int | None) -> int:
    """Token change from the admin: set an exact number or add / remove some; never below 0."""
    if set_to is not None:
        return max(0, set_to)
    return max(0, current + (add or 0))


# --- users ---

def list_users(status: str | None = None) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    runs = select(Run.user_id, func.count().label("n")).group_by(Run.user_id).subquery()
    sessions = (select(Session.user_id, func.count().label("n")).where(Session.expires_at > now)
                .group_by(Session.user_id).subquery())
    q = (select(User, func.coalesce(runs.c.n, 0).label("runs"), func.coalesce(sessions.c.n, 0).label("sessions"))
         .outerjoin(runs, runs.c.user_id == User.id).outerjoin(sessions, sessions.c.user_id == User.id)
         .order_by(User.created_at.desc()))
    if status:
        q = q.where(User.status == status)
    with require_engine().connect() as conn:
        rows = conn.execute(q).all()
    return [{"id": r.id, "email": r.email, "role": r.role, "status": r.status, "tokens": r.tokens,
             "has_password": r.password_hash is not None, "google": r.google_sub is not None,
             "locked": bool(r.locked_until and r.locked_until > now), "runs": r.runs, "sessions": r.sessions,
             "created_at": _iso(r.created_at), "approved_at": _iso(r.approved_at),
             "last_login_at": _iso(r.last_login_at)} for r in rows]


def _tester(conn: Connection, user_id: int):
    """The user row, refused for the admin account (admin rows are not changed from the app)."""
    user = conn.execute(select(User).where(User.id == user_id).with_for_update()).first()
    if user is None:
        raise AuthError(404, "not_found", "User not found.")
    if user.role == "admin":
        raise AuthError(403, "admin_account", "The admin account is not changed from here.")
    return user


def approve_user(admin_id: int, user_id: int) -> None:
    tokens = get_config().access.default_tokens
    with require_engine().begin() as conn:
        _tester(conn, user_id)
        conn.execute(update(User).where(User.id == user_id).values(
            status="approved", tokens=tokens, approved_at=datetime.now(timezone.utc)))
        _audit(conn, admin_id, "approve_user", f"user {user_id}", {"tokens": tokens})


def reject_user(admin_id: int, user_id: int) -> None:
    with require_engine().begin() as conn:
        _tester(conn, user_id)
        conn.execute(update(User).where(User.id == user_id).values(status="rejected", tokens=0))
        _audit(conn, admin_id, "reject_user", f"user {user_id}")


def change_tokens(admin_id: int, user_id: int, set_to: int | None, add: int | None) -> int:
    with require_engine().begin() as conn:
        user = _tester(conn, user_id)
        tokens = new_tokens(user.tokens, set_to, add)
        conn.execute(update(User).where(User.id == user_id).values(tokens=tokens))
        _audit(conn, admin_id, "set_tokens", f"user {user_id}", {"from": user.tokens, "to": tokens})
    return tokens


def reset_password(admin_id: int, user_id: int, password: str) -> None:
    """New password set by the owner; the lockout is cleared and the user is signed out everywhere."""
    if len(password) < MIN_PASSWORD:
        raise AuthError(400, "short_password", f"Use at least {MIN_PASSWORD} characters.")
    with require_engine().begin() as conn:
        _tester(conn, user_id)
        conn.execute(update(User).where(User.id == user_id).values(
            password_hash=hash_password(password), failed_logins=0, locked_until=None))
        conn.execute(delete(Session).where(Session.user_id == user_id))
        _audit(conn, admin_id, "reset_password", f"user {user_id}")


def sign_out_user(admin_id: int, user_id: int) -> None:
    with require_engine().begin() as conn:
        _tester(conn, user_id)
        conn.execute(delete(Session).where(Session.user_id == user_id))
        _audit(conn, admin_id, "sign_out_user", f"user {user_id}")


def delete_user(admin_id: int, user_id: int) -> None:
    """Only a user without runs (P5): runs keep their owner for the record."""
    with require_engine().begin() as conn:
        user = _tester(conn, user_id)
        if conn.execute(select(func.count()).select_from(Run).where(Run.user_id == user_id)).scalar_one():
            raise AuthError(409, "has_runs", "This user has runs. Reject or sign out instead.")
        conn.execute(delete(User).where(User.id == user_id))
        _audit(conn, admin_id, "delete_user", f"user {user_id}", {"email": user.email})


# --- runs ---

def list_runs(status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    # last step that finished, for "stopped after …" (owner, 12 Nov)
    last_step = (select(NodeRun.node).where(NodeRun.run_id == Run.id, NodeRun.status == "done")
                 .order_by(NodeRun.finished_at.desc()).limit(1).scalar_subquery())
    q = (select(Run.id, Run.original_filename, Run.status, Run.failed_at, Run.error, Run.created_at, Run.updated_at,
                Run.git_commit, User.email, last_step.label("last_step")).outerjoin(User, User.id == Run.user_id)
         .order_by(Run.created_at.desc()).limit(limit))
    if status:
        q = q.where(Run.status == status)
    with require_engine().connect() as conn:
        return [{"run_id": r.id, "file": r.original_filename, "status": r.status, "failed_at": r.failed_at,
                 "error": r.error, "user": r.email, "last_step": r.last_step, "created_at": _iso(r.created_at),
                 "updated_at": _iso(r.updated_at), "git_commit": r.git_commit} for r in conn.execute(q)]


def step_status(node: str, status: str, finished_at: datetime | None) -> str:
    """An open confirm step is the run waiting for the user, not work in progress (owner, 12 Nov)."""
    return "awaiting_confirm" if node == "confirm" and status == "running" and finished_at is None else status


def run_steps(run_id: str) -> list[dict[str, Any]]:
    """Every node attempt of a run, oldest first (a re-run or resume adds a row)."""
    with require_engine().connect() as conn:
        if conn.execute(select(Run.id).where(Run.id == run_id)).first() is None:
            raise AuthError(404, "not_found", "Run not found.")
        rows = conn.execute(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.started_at)).all()
    return [{"node": r.node, "status": step_status(r.node, r.status, r.finished_at),
             "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
             "seconds": round((r.finished_at - r.started_at).total_seconds(), 1) if r.finished_at else None,
             "summary": r.summary, "error": r.error} for r in rows]


def node_running(run_id: str) -> bool:
    """A node of this run is working right now (its node_runs row is open; a server stop closes these: H1)."""
    with require_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(NodeRun).where(
            NodeRun.run_id == run_id, NodeRun.status == "running", NodeRun.finished_at.is_(None),
            NodeRun.node != "confirm")).scalar_one() > 0


def _run_row(conn: Connection, run_id: str):
    run = conn.execute(select(Run).where(Run.id == run_id).with_for_update()).first()
    if run is None:
        raise AuthError(404, "not_found", "Run not found.")
    return run


def mark_run_failed(admin_id: int, run_id: str) -> None:
    """A stuck run (e.g. waiting at confirm forever) → failed; frees the user's one-run slot. Resume stays possible."""
    if node_running(run_id):
        raise AuthError(409, "running_now", "A step of this run is running right now. Wait for it to finish.")
    with require_engine().begin() as conn:
        run = _run_row(conn, run_id)
        conn.execute(update(Run).where(Run.id == run_id).values(
            status="failed", failed_at=run.failed_at or "admin", error="Marked failed by the admin",
            updated_at=datetime.now(timezone.utc)))
        _audit(conn, admin_id, "mark_run_failed", f"run {run_id}", {"was": run.status})


def delete_run(admin_id: int, run_id: str, run_folder, forget_checkpoint) -> None:
    """Delete a run's data: its database rows (node results, node tables, node times, events), its paused state
    and its folder. Shared price knowledge (price_figures, search_results) is kept; their first_run_id becomes NULL."""
    if node_running(run_id):
        raise AuthError(409, "running_now", "A step of this run is running right now. Wait for it to finish.")
    with require_engine().begin() as conn:
        run = _run_row(conn, run_id)
        conn.execute(delete(RunEvent).where(RunEvent.run_id == run_id))  # no foreign key on run_events
        conn.execute(delete(Run).where(Run.id == run_id))  # node_runs, node_results, node tables: ON DELETE CASCADE
        _audit(conn, admin_id, "delete_run", f"run {run_id}",
               {"file": run.original_filename, "status": run.status, "user_id": run.user_id})
    forget_checkpoint(run_id)
    shutil.rmtree(run_folder, ignore_errors=True)


# --- audit log ---

def list_audit(action: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    q = (select(AuditLog.id, AuditLog.at, AuditLog.action, AuditLog.target, AuditLog.details, User.email)
         .outerjoin(User, User.id == AuditLog.admin_id).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit))
    if action:
        q = q.where(AuditLog.action == action)
    with require_engine().connect() as conn:
        return [{"id": r.id, "at": _iso(r.at), "admin": r.email, "action": r.action, "target": r.target,
                 "details": r.details} for r in conn.execute(q)]


# --- dashboard (stage 6.4, 06-admin.md §6.6) ---

AI_NODES = ("verify", "photos", "plan", "extract")
TAVILY_FREE_CREDITS = 1000  # Tavily free plan per month (basic search = 1 credit per query)


def dashboard(days: int = 30) -> dict[str, Any]:
    """Numbers for the admin dashboard over the last `days` days (status counts and access: now)."""
    days = max(1, min(days, 365))
    with require_engine().connect() as conn:
        def rows(sql: str, **params) -> list[dict]:
            return [dict(r._mapping) for r in conn.execute(text(sql), {"days": days, **params})]

        runs_per_day = rows("""
            SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date::text AS day, status, count(*) AS n
            FROM runs WHERE created_at > now() - make_interval(days => :days)
            GROUP BY 1, 2 ORDER BY 1""")
        steps = rows("""
            SELECT node,
                   count(*) FILTER (WHERE status = 'done') AS done,
                   count(*) FILTER (WHERE status = 'failed') AS failed,
                   round(avg(extract(epoch FROM finished_at - started_at)) FILTER (WHERE status = 'done')::numeric, 1) AS avg_sec,
                   round(max(extract(epoch FROM finished_at - started_at)) FILTER (WHERE status = 'done')::numeric, 1) AS max_sec
            FROM node_runs WHERE started_at > now() - make_interval(days => :days) AND node NOT IN ('upload', 'confirm')
            GROUP BY node""")
        last_errors = rows("""
            SELECT node, run_id, error, finished_at::text AS at FROM node_runs
            WHERE status = 'failed' AND started_at > now() - make_interval(days => :days)
            ORDER BY finished_at DESC NULLS LAST LIMIT 10""")
        models = rows("""
            SELECT node, data->'answered_by'->>'model' AS model,
                   count(*) AS answers,
                   count(*) FILTER (WHERE jsonb_array_length(coalesce(data->'attempts', '[]')) > 1) AS after_fallback
            FROM node_results
            WHERE name = 'response.json' AND node = ANY(:nodes) AND saved_at > now() - make_interval(days => :days)
            GROUP BY 1, 2 ORDER BY 1, 3 DESC""", nodes=list(AI_NODES))
        tavily = conn.execute(text("""
            SELECT coalesce(sum((SELECT count(*) FROM plan_queries q WHERE q.run_id = n.run_id)), 0)
            FROM node_runs n
            WHERE n.node = 'search' AND n.status = 'done'
              AND n.started_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'""")).scalar_one()
        access = rows("""
            SELECT count(*) FILTER (WHERE status = 'pending' AND role = 'tester') AS pending,
                   count(*) FILTER (WHERE status = 'approved' AND role = 'tester') AS approved,
                   count(*) FILTER (WHERE locked_until > now()) AS locked
            FROM users""")[0]
        tokens = rows("""
            SELECT u.email, u.tokens AS tokens_left, count(r.id) AS runs
            FROM users u LEFT JOIN runs r ON r.user_id = u.id
            WHERE u.role = 'tester' AND u.status = 'approved'
            GROUP BY u.id ORDER BY runs DESC, u.email LIMIT 50""")
        prices = rows("""
            SELECT coalesce(p.status, 'none') AS status, count(*) AS n FROM prices p JOIN runs r ON r.id = p.run_id
            WHERE r.created_at > now() - make_interval(days => :days) GROUP BY 1""")
        now_runs = rows("""
            SELECT r.id AS run_id, r.status, r.original_filename AS file, u.email AS user, r.updated_at::text AS since
            FROM runs r LEFT JOIN users u ON u.id = r.user_id
            WHERE r.status IN ('uploaded', 'running', 'awaiting_confirm') ORDER BY r.updated_at DESC LIMIT 50""")
    langfuse = os.environ.get("LANGFUSE_HOST", "").strip() or None
    return {"days": days, "runs_per_day": runs_per_day, "steps": steps, "last_errors": last_errors, "models": models,
            "tavily": {"queries_this_month": int(tavily), "free_credits": TAVILY_FREE_CREDITS,
                       "note": "approximate: search runs this month x their plan queries (1 credit each, basic)"},
            "access": access, "tokens": tokens, "prices": prices, "in_progress": now_runs, "langfuse_url": langfuse}


# --- table browser (stage 6.4, 06-admin.md §6.7): read-only, allow-listed tables, secrets masked ---

SECRET_COLUMNS = {("users", "password_hash"), ("users", "totp_secret"), ("sessions", "key_hash")}
PAGE_SIZE = 50
CELL_CHARS = 400  # long text / JSON cells are cut in the list (full JSON: the run's files in the Runs page)


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    if table is None:
        raise AuthError(404, "not_found", "Unknown table.")
    return table


def list_tables() -> list[dict[str, Any]]:
    with require_engine().connect() as conn:
        return [{"name": name, "rows": conn.execute(select(func.count()).select_from(t)).scalar_one(),
                 "columns": [c.name for c in t.columns]}
                for name, t in sorted(Base.metadata.tables.items())]


def _cell(table: str, column: str, value: Any) -> Any:
    if (table, column) in SECRET_COLUMNS:
        return None if value is None else "•••"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and len(value) > CELL_CHARS:
        return value[:CELL_CHARS] + f"… ({len(value):,} chars)"
    return value


def table_rows(name: str, page: int = 1, sort: str | None = None, desc: bool = True, search: str | None = None,
               column: str | None = None, value: str | None = None) -> dict[str, Any]:
    """One page of a table. sort / column must be real column names (checked); search looks in every text column."""
    table = _table(name)
    cols = {c.name: c for c in table.columns}
    q = select(table)
    if search:
        texts = [c for c in table.columns if isinstance(c.type, (Text, String)) and (name, c.name) not in SECRET_COLUMNS]
        q = q.where(or_(*[c.ilike(f"%{search}%") for c in texts])) if texts else q.where(false())
    if column:
        if column not in cols or (name, column) in SECRET_COLUMNS:
            raise AuthError(400, "bad_column", f"No column {column} to filter on.")
        q = q.where(cast(cols[column], Text).ilike(f"%{value or ''}%"))
    order = cols.get(sort) if sort else next(iter(table.primary_key.columns), None)
    if sort and order is None:
        raise AuthError(400, "bad_column", f"No column {sort} to sort by.")
    if order is not None:
        q = q.order_by(order.desc() if desc else order.asc())
    page = max(1, page)
    with require_engine().connect() as conn:
        total = conn.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        rows = conn.execute(q.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).all()
    return {"table": name, "columns": list(cols), "page": page, "page_size": PAGE_SIZE, "total": total,
            "rows": [{k: _cell(name, k, v) for k, v in r._mapping.items()} for r in rows]}
