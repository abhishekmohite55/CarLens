"""H1: nodes cut off by a server stop are found and closed once; confirm (waiting on purpose) is not (stage 2.5b)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import run_index


def test_open_nodes_are_found_then_closed(db_engine):
    t = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    run_id = run_index.create_run_row(sha256="ee" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    for node in ("verify", "confirm"):
        run_index.record_node_event({"run_id": run_id, "node": node, "type": "node_started", "data": {}}, t)

    mine = [n for r, n in run_index.interrupted_nodes() if r == run_id]
    assert mine == ["verify"]

    run_index.close_open_rows(run_id, "verify", "Server stopped while this node was running", t)
    assert [n for r, n in run_index.interrupted_nodes() if r == run_id] == []
