"""Node outputs in the database (platform step 2): what used to be JSON files in the run folder.

Callers keep using the old file path as the name, so the API and the inspector see the same JSON.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from .db import get_engine, require_engine
from .models import NodeResult
from .node_tables import NODE_TABLES, WRITERS
from .runs import run_dir

# Run-folder path → (node, name) row in node_results. One node more per stage 2.x.
FILES: dict[str, tuple[str, str]] = {
    "meta.json": ("upload", "meta.json"),
    "01_locate/request.json": ("locate", "request.json"),
    "01_locate/response.json": ("locate", "response.json"),
    "02_frames/manifest.json": ("frames", "manifest.json"),
    "03_verify/ocr.json": ("verify", "ocr.json"),
    "03_verify/request.json": ("verify", "request.json"),
    "03_verify/response.json": ("verify", "response.json"),
    "04_confirm_payload.json": ("confirm", "04_confirm_payload.json"),
    "04_confirm.json": ("confirm", "04_confirm.json"),
    "05_photos/request.json": ("photos", "request.json"),
    "05_photos/response.json": ("photos", "response.json"),
    "05_photos/applied.json": ("photos", "applied.json"),
    "06_plan/request.json": ("plan", "request.json"),
    "06_plan/response.json": ("plan", "response.json"),
    "06_plan/queries.json": ("plan", "queries.json"),
    "07_search/results.json": ("search", "results.json"),
}


def save_result(run_id: str, path: str, data: Any) -> None:
    node, name = FILES[path]
    stmt = insert(NodeResult).values(run_id=run_id, node=node, name=name, data=data)
    stmt = stmt.on_conflict_do_update(index_elements=["run_id", "node", "name"],
                                      set_={"data": stmt.excluded.data, "saved_at": func.now()})
    with require_engine().begin() as conn:
        conn.execute(stmt)
        if path in WRITERS:  # same transaction: the clean table matches the saved JSON
            WRITERS[path](conn, run_id, data)


def delete_results(run_id: str, node: str) -> None:
    """Remove a node's saved rows before it runs again (re-run, resume)."""
    with require_engine().begin() as conn:
        conn.execute(delete(NodeResult).where(NodeResult.run_id == run_id, NodeResult.node == node))
        for table in NODE_TABLES.get(node, []):
            conn.execute(delete(table).where(table.run_id == run_id))


def load_result(run_id: str, path: str) -> Any | None:
    """The saved JSON, or None when the node has not saved it."""
    node, name = FILES[path]
    engine = get_engine()
    if engine is not None:
        with engine.connect() as conn:
            row = conn.execute(select(NodeResult.data).where(
                NodeResult.run_id == run_id, NodeResult.node == node, NodeResult.name == name)).first()
        if row is not None:
            return row[0]
    # shortcut: runs from before step 2 only have the file; remove after they are imported (D4)
    old = run_dir(run_id) / path
    if old.exists():
        return json.loads(old.read_text(encoding="utf-8"))
    return None
