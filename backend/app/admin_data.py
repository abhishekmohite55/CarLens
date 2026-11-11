"""Admin actions and lists (platform step 6, docs/platform/06-admin.md §6.4, §6.5, §6.8).

Every change writes its audit_log row in the same transaction. Rules live here, not in the screens.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection

from .auth import AuthError, hash_password
from .config import get_config
from .db import require_engine
from .models import AuditLog, NodeRun, Run, RunEvent, Session, User
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
