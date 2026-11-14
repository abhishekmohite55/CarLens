"""Tokens, one run at a time, own runs only, same video again (platform stage 5.3); needs carlens_test.
The video checks (OpenCV) are replaced by a stub: these tests are about the rules, not the video."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
VIDEO = {"video": ("car.mp4", b"x", "video/mp4")}


@pytest.fixture
def env(db_engine, tmp_path, monkeypatch):
    import app.nodes.upload as upload_mod
    import app.runs as runs_mod
    import app.main as main_mod
    for mod in (runs_mod, main_mod):  # main.py imported run_dir by name
        monkeypatch.setattr(mod, "run_dir", lambda rid: tmp_path / "runs" / rid)
    monkeypatch.setattr(upload_mod, "_pending_root", lambda: tmp_path / "pending")
    shas = {"sha": "a" * 64}

    async def fake_receive(video):
        p = tmp_path / f"{uuid4().hex}.mp4"
        p.write_bytes(b"x")
        return upload_mod.Received(p, "car.mp4", "mp4", 1, shas["sha"], 60.0)

    monkeypatch.setattr(upload_mod, "receive_upload", fake_receive)
    from app.main import app
    return db_engine, app, shas, tmp_path


def _tester(db_engine, app, tokens):
    from app.auth import hash_password
    from app.models import User
    email = f"t{uuid4().hex[:10]}@runs.test"
    with db_engine.begin() as conn:
        conn.execute(insert(User).values(email=email, password_hash=hash_password("tester password 1"),
                                         role="tester", status="approved", tokens=tokens))
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": email, "password": "tester password 1"}, headers=ORIGIN).status_code == 200
    return client


def _finish(db_engine, run_id):
    from app.models import Run
    with db_engine.begin() as conn:
        conn.execute(update(Run).where(Run.id == run_id).values(status="partial"))


def _tokens(client):
    return client.get("/api/auth/me").json()["tokens"]


def test_one_token_per_run_and_one_run_at_a_time(env):
    db_engine, app, shas, _ = env
    client = _tester(db_engine, app, tokens=2)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    assert _tokens(client) == 1

    shas["sha"] = "b" * 64
    r = client.post("/api/runs", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_in_progress"
    assert _tokens(client) == 1  # refused: no token spent

    _finish(db_engine, run1)
    run2 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    assert _tokens(client) == 0
    _finish(db_engine, run2)

    shas["sha"] = "c" * 64
    r = client.post("/api/runs", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_tokens"


def test_users_see_only_their_own_runs(env):
    db_engine, app, shas, _ = env
    shas["sha"] = uuid4().hex * 2
    alice = _tester(db_engine, app, tokens=1)
    bob = _tester(db_engine, app, tokens=1)
    run_id = alice.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]

    assert alice.get(f"/api/runs/{run_id}").status_code == 200
    assert [r["run_id"] for r in alice.get("/api/runs").json()["runs"]] == [run_id]
    assert bob.get(f"/api/runs/{run_id}").status_code == 404
    assert bob.get(f"/api/runs/{run_id}/files/meta.json").status_code == 404
    assert bob.get("/api/runs").json()["runs"] == []
    assert alice.post(f"/api/runs/{run_id}/locate", headers=ORIGIN).status_code == 403  # dev routes: admin only


def test_same_video_again_asks_first(env):
    db_engine, app, shas, tmp_path = env
    shas["sha"] = uuid4().hex * 2
    client = _tester(db_engine, app, tokens=3)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    _finish(db_engine, run1)

    r = client.post("/api/runs", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["duplicate_of"] == run1
    assert _tokens(client) == 2  # asking costs nothing
    pending = r.json()["pending_id"]
    assert (tmp_path / "pending" / pending).exists()
    assert client.delete(f"/api/uploads/{pending}", headers=ORIGIN).status_code == 200  # "open old run"
    assert not (tmp_path / "pending" / pending).exists()

    pending = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["pending_id"]
    other = _tester(db_engine, app, tokens=1)
    assert other.post(f"/api/uploads/{pending}/start", headers=ORIGIN).status_code == 404  # not theirs
    r = client.post(f"/api/uploads/{pending}/start", headers=ORIGIN)  # "fresh run"
    assert r.status_code == 200 and r.json()["run_id"] != run1
    assert _tokens(client) == 1

    from app.models import Run
    with db_engine.connect() as conn:
        owner = conn.execute(select(Run.user_id).where(Run.id == r.json()["run_id"])).scalar_one()
    assert owner is not None


def test_end_a_run_that_never_started(env):
    """F9: a video uploaded but never started can be ended (no token back), then a fresh run is allowed."""
    db_engine, app, shas, _ = env
    client = _tester(db_engine, app, tokens=2)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    other = _tester(db_engine, app, tokens=1)
    assert other.post(f"/api/runs/{run1}/end", headers=ORIGIN).status_code == 404  # not their run

    assert client.post(f"/api/runs/{run1}/end", headers=ORIGIN).json() == {"ended": True}
    assert _tokens(client) == 1  # the token is not given back
    statuses = {r["run_id"]: r["status"] for r in client.get("/api/runs").json()["runs"]}
    assert statuses[run1] == "partial"
    r = client.post(f"/api/runs/{run1}/end", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_started"

    shas["sha"] = "d" * 64
    run2 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]  # the slot is free again
    _finish(db_engine, run2)
    assert client.post(f"/api/runs/{run2}/end", headers=ORIGIN).status_code == 409  # not "uploaded" any more
