from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_config, PROJECT_ROOT

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
    event = {
        "seq": next_seq(run_id),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "node": node,
        "type": type_,
        "data": data,
    }
    with open(events_path(run_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event
