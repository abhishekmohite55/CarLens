"""Node outputs saved in node_results (platform stage 2.1)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import results, run_index


def test_save_then_load_returns_the_same_json_and_overwrites(db_engine):
    run_id = run_index.create_run_row(sha256="ef" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "meta.json", {"run_id": run_id, "duration_sec": 61.5})
    results.save_result(run_id, "meta.json", {"run_id": run_id, "duration_sec": 62.0})
    assert results.load_result(run_id, "meta.json") == {"run_id": run_id, "duration_sec": 62.0}


def test_old_run_without_a_row_still_loads_its_file(tmp_path, monkeypatch):
    run_id = "r_20261105_083146_81b6"
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "meta.json").write_text(json.dumps({"duration_sec": 132.7}), encoding="utf-8")
    monkeypatch.setattr(results, "run_dir", lambda rid: tmp_path / rid)
    monkeypatch.setattr(results, "get_engine", lambda: None)

    assert results.load_result(run_id, "meta.json") == {"duration_sec": 132.7}
