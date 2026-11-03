"""Tests for runs.py helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.runs as runs_mod


def test_next_seq_continues_from_existing_events(tmp_path, monkeypatch):
    """next_seq seeds from existing events.jsonl line count on first call after a restart."""
    run_id = "r_test_seq_cont_0001"
    run_folder = tmp_path / run_id
    run_folder.mkdir()
    (run_folder / "events.jsonl").write_text(
        '{"seq":1}\n{"seq":2}\n{"seq":3}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(runs_mod, "run_dir", lambda rid: tmp_path / rid)
    runs_mod._seq.pop(run_id, None)

    assert runs_mod.next_seq(run_id) == 4


def test_next_seq_starts_at_1_for_new_run(tmp_path, monkeypatch):
    run_id = "r_test_seq_new_0002"
    run_folder = tmp_path / run_id
    run_folder.mkdir()
    # No events.jsonl → starts at 1

    monkeypatch.setattr(runs_mod, "run_dir", lambda rid: tmp_path / rid)
    runs_mod._seq.pop(run_id, None)

    assert runs_mod.next_seq(run_id) == 1
