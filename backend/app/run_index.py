"""Run index (platform stage 2.1): runs rows, node_runs rows from events, run ids, git commit.

Only this module writes `runs` and `node_runs`.
"""
from __future__ import annotations

import os
import secrets
import string
import subprocess
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .config import PROJECT_ROOT
from .db import require_engine
from .models import NodeRun, Run

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


def create_run_row(*, sha256: str, original_filename: str, size_bytes: int, duration_sec: float) -> str:
    """Insert the runs row under a new random id and return the id. A clash draws a new id."""
    engine = require_engine()
    commit = git_commit()
    for _ in range(5):
        run_id = new_run_id()
        try:
            with engine.begin() as conn:
                conn.execute(insert(Run).values(
                    id=run_id, video_sha256=sha256, original_filename=original_filename,
                    size_bytes=size_bytes, duration_sec=duration_sec, git_commit=commit))
            return run_id
        except IntegrityError:
            continue
    raise RuntimeError("Could not draw a free run id")


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
