from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import insert

from .config import get_config, PROJECT_ROOT
from .db import get_engine
from .models import RunEvent

log = logging.getLogger(__name__)

_seq: dict[str, int] = {}


def new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(2)  # 4 hex chars
    return f"r_{ts}_{suffix}"


def run_dir(run_id: str) -> Path:
    cfg = get_config()
    return PROJECT_ROOT / cfg.paths.runs_dir / run_id


def create_run(run_id: str) -> Path:
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=False)
    return d


def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def next_seq(run_id: str) -> int:
    if run_id not in _seq:
        ep = events_path(run_id)
        if ep.exists():
            with open(ep, encoding="utf-8") as f:
                _seq[run_id] = sum(1 for line in f if line.strip())
        else:
            _seq[run_id] = 0
    _seq[run_id] += 1
    return _seq[run_id]


def events_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def append_event(run_id: str, node: str, type_: str, data: dict) -> dict:
    now = datetime.now(timezone.utc)
    event = {
        "seq": next_seq(run_id),
        "ts": now.isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "node": node,
        "type": type_,
        "data": data,
    }
    with open(events_path(run_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    _record_event(event, now)
    return event


def _record_event(event: dict, ts: datetime) -> None:
    """Copy one event into run_events (platform stage 2.0). The file stays the source for the live page.
    A database problem is logged and never stops a run."""
    engine = get_engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(insert(RunEvent).values(
                run_id=event["run_id"], seq=event["seq"], ts=ts,
                node=event["node"], type=event["type"], data=event["data"]))
    except Exception as e:
        log.warning("run_events write failed (run %s, seq %s): %s", event["run_id"], event["seq"], e)


TERMINAL = {"node_done": "done", "node_failed": "failed", "node_skipped": "skipped"}


def read_events(run_id: str) -> list[dict]:
    ep = events_path(run_id)
    if not ep.exists():
        return []
    out = []
    with open(ep, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def node_result(run_id: str, node: str, after_seq: int = 0) -> dict | None:
    """The node's last done/failed/skipped event after after_seq, or None if it emitted none."""
    hits = [e for e in read_events(run_id)
            if e.get("node") == node and e.get("type") in TERMINAL and e.get("seq", 0) > after_seq]
    return hits[-1] if hits else None


def failed_at(run_id: str) -> str | None:
    """Node the run stopped at, from the last run_done event; None when the last run did not fail."""
    done = [e for e in read_events(run_id) if e.get("node") == "pipeline" and e.get("type") == "run_done"]
    data = done[-1].get("data", {}) if done else {}
    return data.get("failed_at") if data.get("status") == "failed" else None
