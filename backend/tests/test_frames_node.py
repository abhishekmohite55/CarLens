"""Tests for nodes/frames.py: locate-result loading and the one-run-at-a-time claim."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import results
from app.nodes import frames as frames_node

RUN = "r_test_frames_old"  # no database row: load_result falls back to the old file


def _old_run(tmp_path, monkeypatch, parsed=None, write=True) -> None:
    monkeypatch.setattr(results, "run_dir", lambda rid: tmp_path / rid)
    monkeypatch.setattr(results, "get_engine", lambda: None)
    if write:
        (tmp_path / RUN / "01_locate").mkdir(parents=True)
        (tmp_path / RUN / "01_locate" / "response.json").write_text(json.dumps({"parsed": parsed}), encoding="utf-8")


def test_load_locate_items_missing_file(tmp_path, monkeypatch):
    _old_run(tmp_path, monkeypatch, write=False)
    assert frames_node.load_locate_items(RUN) is None


def test_load_locate_items_parsed_null(tmp_path, monkeypatch):
    _old_run(tmp_path, monkeypatch, None)
    assert frames_node.load_locate_items(RUN) is None


def test_load_locate_items_ok(tmp_path, monkeypatch):
    items = [{"id": "L1", "category": "plate", "t": 1.0}]
    _old_run(tmp_path, monkeypatch, {"items": items, "coverage": {}})
    assert frames_node.load_locate_items(RUN) == items


def test_load_locate_items_from_database(db_engine):
    from app import run_index

    run_id = run_index.create_run_row(sha256="aa" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    items = [{"id": "L1", "category": "odometer", "t": 59.5}]
    results.save_result(run_id, "01_locate/response.json", {"parsed": {"items": items, "coverage": {}}})
    assert frames_node.load_locate_items(run_id) == items
    results.delete_results(run_id, "locate")
    assert results.load_result(run_id, "01_locate/response.json") is None


def test_try_claim_blocks_second_run():
    run_id = "r_test_claim_0001"
    frames_node._running.discard(run_id)
    assert frames_node.try_claim(run_id) is True
    assert frames_node.try_claim(run_id) is False
    frames_node._running.discard(run_id)
