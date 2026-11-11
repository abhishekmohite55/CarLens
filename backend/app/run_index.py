"""Run index (platform stage 2.1): runs rows, node_runs rows from events, run ids, git commit.

Only this module writes `runs` and `node_runs`.
"""
from __future__ import annotations

import os
import secrets
import string
import subprocess
from datetime import datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .config import PROJECT_ROOT
from .db import require_engine
from .models import NodeRun, Run, User

TERMINAL = {"node_done": "done", "node_failed": "failed", "node_skipped": "skipped"}

_ID_CHARS = string.ascii_lowercase + string.digits


def new_run_id() -> str:
    """r_ + 12 random letters/digits (owner, 10 Nov 2026: no date, no sha256; uniqueness from the primary key)."""
    return "r_" + "".join(secrets.choice(_ID_CHARS) for _ in range(12))


def git_commit() -> str | None:
    """Short commit of the code that runs, + '-dirty' when files differ from it.
    Without git (the container) the commit baked in at build time (CARLENS_GIT_COMMIT), else None."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
                               timeout=5, check=True).stdout.strip()
    try:
        return git("rev-parse", "--short", "HEAD") + ("-dirty" if git("status", "--porcelain") else "")
    except Exception:
        return os.environ.get("CARLENS_GIT_COMMIT") or None


# A run in one of these states is the user's "run in progress" (paused at confirm counts: owner F5).
ACTIVE_STATUSES = ("uploaded", "running", "awaiting_confirm")


class RunRefused(Exception):
    """A tester may not start a run now (platform step 5, 05-login.md §7.2)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def run_refusal(active_runs: int, tokens: int) -> RunRefused | None:
    """One run at a time, and a token for each new run."""
    if active_runs > 0:
        return RunRefused(409, "run_in_progress", "You already have a run in progress. Wait until it is finished.")
    if tokens <= 0:
        return RunRefused(403, "no_tokens", "You have no runs left. Ask the owner for more.")
    return None


def create_run_row(*, sha256: str, original_filename: str, size_bytes: int, duration_sec: float,
                   user_id: int | None = None, spend_token: bool = False) -> str:
    """Insert the runs row under a new random id and return the id. A clash draws a new id.
    spend_token (testers): in the same transaction, check one run at a time and take 1 token; raises RunRefused."""
    engine = require_engine()
    commit = git_commit()
    for _ in range(5):
        run_id = new_run_id()
        try:
            with engine.begin() as conn:
                if spend_token:
                    tokens = conn.execute(select(User.tokens).where(User.id == user_id).with_for_update()).scalar_one()
                    active = conn.execute(select(func.count()).select_from(Run).where(
                        Run.user_id == user_id, Run.status.in_(ACTIVE_STATUSES))).scalar_one()
                    refused = run_refusal(active, tokens)
                    if refused:
                        raise refused
                    conn.execute(update(User).where(User.id == user_id).values(tokens=User.tokens - 1))
                conn.execute(insert(Run).values(
                    id=run_id, video_sha256=sha256, original_filename=original_filename,
                    size_bytes=size_bytes, duration_sec=duration_sec, git_commit=commit, user_id=user_id))
            return run_id
        except IntegrityError:
            continue
    raise RuntimeError("Could not draw a free run id")


def run_owner(run_id: str) -> tuple[bool, int | None]:
    """(run exists, its user id)."""
    with require_engine().connect() as conn:
        row = conn.execute(select(Run.user_id).where(Run.id == run_id)).first()
    return (row is not None, row.user_id if row else None)


def user_runs(user_id: int | None, limit: int = 50) -> list[dict]:
    """Newest runs of one user (None = every run, for the admin)."""
    q = select(Run.id, Run.original_filename, Run.status, Run.failed_at, Run.created_at).order_by(
        Run.created_at.desc()).limit(limit)
    if user_id is not None:
        q = q.where(Run.user_id == user_id)
    with require_engine().connect() as conn:
        return [{"run_id": r.id, "file": r.original_filename, "status": r.status, "failed_at": r.failed_at,
                 "created_at": r.created_at.isoformat()} for r in conn.execute(q)]


def user_run_with_video(user_id: int, sha256: str) -> str | None:
    """The user's newest run of this video (same sha256), if any."""
    with require_engine().connect() as conn:
        return conn.execute(select(Run.id).where(Run.user_id == user_id, Run.video_sha256 == sha256)
                            .order_by(Run.created_at.desc()).limit(1)).scalar_one_or_none()


def other_active_run(user_id: int, run_id: str) -> bool:
    """True when the user has a run in progress other than this one (resume must not make it two)."""
    with require_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(Run).where(
            Run.user_id == user_id, Run.id != run_id, Run.status.in_(ACTIVE_STATUSES))).scalar_one() > 0


def record_node_event(event: dict, ts: datetime) -> None:
    """Keep node_runs and runs.status in step with one event. Raises on a database error (caller logs it)."""
    run_id, node, type_ = event["run_id"], event["node"], event["type"]
    data = event.get("data") or {}
    with require_engine().begin() as conn:
        if type_ == "node_started":
            conn.execute(insert(NodeRun).values(run_id=run_id, node=node, status="running", started_at=ts))
            if node != "upload":
                conn.execute(update(Run).where(Run.id == run_id).values(
                    status="running", failed_at=None, error=None, updated_at=ts))
        elif type_ in TERMINAL:
            values = {"status": TERMINAL[type_], "finished_at": ts,
                      "summary": data.get("summary") or data.get("reason"), "error": data.get("error")}
            open_id = conn.execute(
                select(NodeRun.id).where(NodeRun.run_id == run_id, NodeRun.node == node, NodeRun.finished_at.is_(None))
                .order_by(NodeRun.id.desc()).limit(1)).scalar()
            if open_id is not None:
                conn.execute(update(NodeRun).where(NodeRun.id == open_id).values(**values))
            else:  # e.g. skipped without a start event
                conn.execute(insert(NodeRun).values(run_id=run_id, node=node, started_at=ts, **values))
        elif type_ == "awaiting_confirm":
            conn.execute(update(Run).where(Run.id == run_id).values(status="awaiting_confirm", updated_at=ts))
        elif type_ == "run_done":
            conn.execute(update(Run).where(Run.id == run_id).values(
                status=data.get("status"), failed_at=data.get("failed_at"), error=data.get("error"), updated_at=ts))

def interrupted_nodes() -> list[tuple[str, str]]:
    """(run_id, node) still marked running: the server stopped in the middle of them (H1).
    Confirm is left out: it waits for the user on purpose and survives a restart."""
    with require_engine().connect() as conn:
        return [tuple(r) for r in conn.execute(
            select(NodeRun.run_id, NodeRun.node)
            .where(NodeRun.finished_at.is_(None), NodeRun.status == "running", NodeRun.node != "confirm")
            .distinct())]


def close_open_rows(run_id: str, node: str, error: str, ts: datetime) -> None:
    """Mark every still-open row of this node failed (older leftovers too), so it is not reported again."""
    with require_engine().begin() as conn:
        conn.execute(update(NodeRun).where(NodeRun.run_id == run_id, NodeRun.node == node,
                                           NodeRun.finished_at.is_(None))
                     .values(status="failed", finished_at=ts, error=error))
