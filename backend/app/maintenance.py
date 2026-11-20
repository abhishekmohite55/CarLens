"""Maintenance mode during a deploy (platform step 9, docs/platform/09-cd.md §5a).

While it is on, nobody (admin too) starts new work: upload, fresh run, Resume, admin re-runs. Runs waiting at confirm
may still be confirmed for maintenance.confirm_grace_min. The deploy waits for working runs (`wait`), at most
maintenance.max_wait_min, deploys, and switches maintenance off. The flag lives in the database (app_state, one row),
so it survives the backend restart of the deploy itself.

    python -m app.maintenance on --by "deploy 3590f55"
    python -m app.maintenance wait          # returns when it is safe to restart (or the wait is over)
    python -m app.maintenance off --by "deploy 3590f55"
    python -m app.maintenance status        # JSON
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import get_config
from .db import get_engine, require_engine
from .models import AppState, AuditLog, Run
from .run_index import RunRefused

MESSAGE = "CarLens is being updated. Try again in a few minutes."
_CHECK_EVERY_SEC = 10


# --- pure rules (tested without a database) ---

def confirm_open(on: bool, since: datetime | None, now: datetime, grace_min: int) -> bool:
    """Confirm is allowed unless maintenance has been on longer than the grace time."""
    return not on or since is None or now - since < timedelta(minutes=grace_min)


def ready_to_restart(running: int, at_confirm: int, since: datetime | None, now: datetime, grace_min: int) -> bool:
    """Safe to restart: nothing working, and nobody can still confirm (or nobody waits at confirm)."""
    return running == 0 and (at_confirm == 0 or not confirm_open(True, since, now, grace_min))


# --- database ---

def expired(since: datetime | None, now: datetime, auto_off_min: int) -> bool:
    """Safety net (step 9.3): maintenance switched on longer ago than auto_off_min counts as off."""
    return since is not None and now - since >= timedelta(minutes=auto_off_min)


def state() -> dict:
    """{"on", "since", "by", "expired"}; off when there is no database, no row yet, or it is older than auto_off_min.
    Never raises: a database problem is health's to report, not a reason to refuse every request."""
    off = {"on": False, "since": None, "by": None, "expired": False}
    engine = get_engine()
    if engine is None:
        return off
    try:
        with engine.connect() as conn:
            row = conn.execute(select(AppState).where(AppState.id == 1)).first()
    except Exception:  # noqa: BLE001  e.g. table missing (database older than this code), database down
        return off
    if row is None or not row.maintenance:
        return off
    if expired(row.maintenance_since, datetime.now(timezone.utc), get_config().maintenance.auto_off_min):
        return {**off, "since": row.maintenance_since, "by": row.maintenance_by, "expired": True}
    return {"on": True, "since": row.maintenance_since, "by": row.maintenance_by, "expired": False}


def set_maintenance(on: bool, by: str) -> None:
    now = datetime.now(timezone.utc)
    values = {"maintenance": on, "maintenance_since": now if on else None, "maintenance_by": by}
    with require_engine().begin() as conn:
        conn.execute(pg_insert(AppState).values(id=1, **values)
                     .on_conflict_do_update(index_elements=[AppState.id], set_=values))
        conn.execute(insert(AuditLog).values(admin_id=None, action="maintenance_on" if on else "maintenance_off",
                                             target="app", details={"by": by}))


def counts(stale_confirm_min: int | None = None) -> dict:
    """Working runs, and runs that reached confirm recently (older ones are left for after the update)."""
    stale = stale_confirm_min if stale_confirm_min is not None else get_config().maintenance.stale_confirm_min
    recent = datetime.now(timezone.utc) - timedelta(minutes=stale)
    with require_engine().connect() as conn:
        running = conn.execute(select(func.count()).where(Run.status == "running")).scalar_one()
        at_confirm = conn.execute(select(func.count()).where(Run.status == "awaiting_confirm",
                                                             Run.updated_at >= recent)).scalar_one()
    return {"running": running, "at_confirm": at_confirm}


# --- used by the routes ---

UNAVAILABLE = "CarLens is temporarily unavailable. Try again later."


def refuse_new_work() -> None:
    """Route dependency: no new upload / fresh run / Resume / re-run while maintenance is on, or while the backend
    started degraded (step 9.3: migration failed, database not reachable)."""
    if state()["on"]:
        raise RunRefused(503, "maintenance", MESSAGE)
    from .health import is_degraded  # imported here: health imports this module
    if is_degraded():
        raise RunRefused(503, "unavailable", UNAVAILABLE)


def refuse_late_confirm() -> None:
    """Route dependency for confirm: allowed during the grace time."""
    s = state()
    if not confirm_open(s["on"], s["since"], datetime.now(timezone.utc), get_config().maintenance.confirm_grace_min):
        raise RunRefused(503, "maintenance", MESSAGE)


# --- command line (deploy) ---

def wait() -> None:
    """Return when no run is working (runs that reached confirm in the last stale_confirm_min count only during the
    grace time), or after max_wait_min."""
    started = time.monotonic()
    while True:
        cfg = get_config().maintenance
        c, s = counts(cfg.stale_confirm_min), state()
        now = datetime.now(timezone.utc)
        if ready_to_restart(c["running"], c["at_confirm"], s["since"] or now, now, cfg.confirm_grace_min):
            print(f"ready: {c['running']} working, {c['at_confirm']} at confirm (they can confirm after the update)")
            return
        if time.monotonic() - started >= cfg.max_wait_min * 60:
            print(f"waited {cfg.max_wait_min} min; deploying anyway: {c['running']} working run(s) will show failed "
                  "(Resume is free)")
            return
        print(f"waiting: {c['running']} working, {c['at_confirm']} at confirm", flush=True)
        time.sleep(_CHECK_EVERY_SEC)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("on", "off"):
        sub.add_parser(name).add_argument("--by", default="command line")
    sub.add_parser("wait")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command in ("on", "off"):
        set_maintenance(args.command == "on", args.by)
        print(f"maintenance {args.command}")
    elif args.command == "wait":
        wait()
    else:
        s = state()
        print(json.dumps({**s, "since": s["since"].isoformat() if s["since"] else None, **counts()}))


if __name__ == "__main__":
    main()
