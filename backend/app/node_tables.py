"""A table per node (option C, owner 10 Nov 2026): the key values of a node's saved JSON as plain rows.

results.save_result() calls the writer for a path in the same transaction as the node_results row,
so the clean table and the exact JSON never disagree. One writer more per stage 2.x.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import delete, insert
from sqlalchemy.engine import Connection

from .models import Frame, LocateItem


def locate_rows(response: dict) -> list[dict]:
    items = ((response or {}).get("parsed") or {}).get("items") or []
    return [{"item_id": i.get("id"), "category": i.get("category"), "label": i.get("label"),
             "side": i.get("side"), "t": i.get("t"), "t_text": i.get("t_text")} for i in items]


def frame_rows(manifest: dict) -> list[dict]:
    rows = []
    for i in (manifest or {}).get("items") or []:
        best = i.get("sharpest") or {}
        rows.append({"item_id": i.get("item_id"), "file": best.get("file"), "t": best.get("t"),
                     "sharpness": best.get("sharpness"), "frames_scored": i.get("frames_extracted"),
                     "skipped": i.get("skipped")})
    return rows


def _replace(model, rows_for: Callable[[Any], list[dict]]):
    def write(conn: Connection, run_id: str, data: Any) -> None:
        conn.execute(delete(model).where(model.run_id == run_id))
        rows = [{"run_id": run_id, **r} for r in rows_for(data)]
        if rows:
            conn.execute(insert(model), rows)
    return write


# Saved path → writer. The node's tables are emptied with its node_results rows (re-run, resume).
WRITERS: dict[str, Callable[[Connection, str, Any], None]] = {
    "01_locate/response.json": _replace(LocateItem, locate_rows),
    "02_frames/manifest.json": _replace(Frame, frame_rows),
}
NODE_TABLES = {"locate": [LocateItem], "frames": [Frame]}
