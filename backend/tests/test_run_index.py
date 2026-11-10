"""Run ids, runs rows and node_runs from events (platform stage 2.1)."""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import run_index


def test_run_id_is_random_without_date():
    ids = {run_index.new_run_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(re.fullmatch(r"r_[a-z0-9]{12}", i) for i in ids)


def test_git_commit_without_git_uses_build_value(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(run_index.subprocess, "run", no_git)
    monkeypatch.setenv("CARLENS_GIT_COMMIT", "abc1234")
    assert run_index.git_commit() == "abc1234"
    monkeypatch.delenv("CARLENS_GIT_COMMIT")
    assert run_index.git_commit() is None


def _event(run_id, node, type_, data=None, seq=1):
    return {"run_id": run_id, "node": node, "type": type_, "data": data or {}, "seq": seq}


def test_node_times_and_run_status_follow_events(db_engine):
    from sqlalchemy import select

    from app.models import NodeRun, Run

    run_id = run_index.create_run_row(sha256="ab" * 32, original_filename="ertiga.mp4",
                                      size_bytes=1234, duration_sec=61.5)
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
    run_index.record_node_event(_event(run_id, "locate", "node_started"), t0)
    run_index.record_node_event(_event(run_id, "locate", "node_failed", {"error": "Gemini 503"}), t0 + timedelta(seconds=30))
    run_index.record_node_event(
        _event(run_id, "pipeline", "run_done", {"status": "failed", "failed_at": "locate", "error": "Gemini 503"}),
        t0 + timedelta(seconds=31))

    with db_engine.connect() as conn:
        run = conn.execute(select(Run).where(Run.id == run_id)).one()
        node = conn.execute(select(NodeRun).where(NodeRun.run_id == run_id)).one()
    assert run.video_sha256 == "ab" * 32 and run.size_bytes == 1234
    assert (run.status, run.failed_at) == ("failed", "locate")
    assert node.status == "failed" and node.error == "Gemini 503"
    assert node.finished_at - node.started_at == timedelta(seconds=30)


def test_rerun_adds_a_new_node_row(db_engine):
    from sqlalchemy import select

    from app.models import NodeRun

    run_id = run_index.create_run_row(sha256="cd" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    t0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    for n in range(2):
        run_index.record_node_event(_event(run_id, "locate", "node_started"), t0 + timedelta(minutes=n))
        run_index.record_node_event(_event(run_id, "locate", "node_done", {"summary": f"try {n}"}),
                                    t0 + timedelta(minutes=n, seconds=10))

    with db_engine.connect() as conn:
        rows = conn.execute(select(NodeRun.summary).where(NodeRun.run_id == run_id).order_by(NodeRun.id)).scalars().all()
    assert rows == ["try 0", "try 1"]
