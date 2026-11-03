"""Tests for nodes/frames.py: locate-result loading and the one-run-at-a-time claim."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.nodes import frames as frames_node


def _write_locate(rd: Path, parsed) -> None:
    (rd / "01_locate").mkdir(parents=True)
    (rd / "01_locate" / "response.json").write_text(json.dumps({"parsed": parsed}), encoding="utf-8")


def test_load_locate_items_missing_file(tmp_path):
    assert frames_node.load_locate_items(tmp_path) is None


def test_load_locate_items_parsed_null(tmp_path):
    _write_locate(tmp_path, None)
    assert frames_node.load_locate_items(tmp_path) is None


def test_load_locate_items_ok(tmp_path):
    items = [{"id": "L1", "category": "plate", "t": 1.0}]
    _write_locate(tmp_path, {"items": items, "coverage": {}})
    assert frames_node.load_locate_items(tmp_path) == items


def test_try_claim_blocks_second_run():
    run_id = "r_test_claim_0001"
    frames_node._running.discard(run_id)
    assert frames_node.try_claim(run_id) is True
    assert frames_node.try_claim(run_id) is False
    frames_node._running.discard(run_id)
