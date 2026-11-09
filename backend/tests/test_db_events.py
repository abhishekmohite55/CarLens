"""run_events copy of every event (platform stage 2.0)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.runs as runs_mod


def _use_tmp_runs(monkeypatch, tmp_path, run_id):
    (tmp_path / run_id).mkdir()
    monkeypatch.setattr(runs_mod, "run_dir", lambda rid: tmp_path / rid)
    runs_mod._seq.pop(run_id, None)


def test_database_error_never_stops_the_event(tmp_path, monkeypatch):
    class BrokenEngine:
        def begin(self):
            raise RuntimeError("database down")

    run_id = "r_test_db_down"
    _use_tmp_runs(monkeypatch, tmp_path, run_id)
    monkeypatch.setattr(runs_mod, "get_engine", lambda: BrokenEngine())

    event = runs_mod.append_event(run_id, "locate", "node_started", {"label": "x"})

    assert event["seq"] == 1
    assert len(runs_mod.read_events(run_id)) == 1


def test_no_database_url_skips_the_copy(tmp_path, monkeypatch):
    run_id = "r_test_db_none"
    _use_tmp_runs(monkeypatch, tmp_path, run_id)
    monkeypatch.setattr(runs_mod, "get_engine", lambda: None)

    assert runs_mod.append_event(run_id, "locate", "node_started", {})["seq"] == 1


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set (database carlens_test)")
def test_event_is_copied_to_run_events(tmp_path, monkeypatch):
    from sqlalchemy import delete, select

    from app.db import get_engine
    from app.models import Base, RunEvent

    engine = get_engine()
    Base.metadata.create_all(engine)
    run_id = "r_test_db_copy"
    with engine.begin() as conn:
        conn.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
    _use_tmp_runs(monkeypatch, tmp_path, run_id)

    first = runs_mod.append_event(run_id, "locate", "node_started", {"label": "Asking Gemini"})
    second = runs_mod.append_event(run_id, "locate", "node_done", {"summary": "13 timestamps"})

    with engine.connect() as conn:
        rows = conn.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).all()
    assert [r.seq for r in rows] == [first["seq"], second["seq"]] == [1, 2]
    assert rows[1].type == "node_done" and rows[1].data == {"summary": "13 timestamps"}
