"""Node outputs saved in node_results (platform stage 2.1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import results, run_index


def test_save_then_load_returns_the_same_json_and_overwrites(db_engine):
    run_id = run_index.create_run_row(sha256="ef" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "meta.json", {"run_id": run_id, "duration_sec": 61.5})
    results.save_result(run_id, "meta.json", {"run_id": run_id, "duration_sec": 62.0})
    assert results.load_result(run_id, "meta.json") == {"run_id": run_id, "duration_sec": 62.0}


def test_no_row_loads_none(monkeypatch):
    monkeypatch.setattr(results, "get_engine", lambda: None)  # no file fallback since the old runs were deleted (10 Nov)
    assert results.load_result("r_20261105_083146_81b6", "meta.json") is None
