"""Tokens, one run at a time, own runs only, same video again (platform stage 5.3); needs carlens_test.
The video checks (OpenCV) are replaced by a stub: these tests are about the rules, not the video."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
VIDEO = {"video": ("car.mp4", b"x", "video/mp4")}


@pytest.fixture
def env(db_engine, tmp_path, monkeypatch):
    import app.nodes.upload as upload_mod
    import app.runs as runs_mod
    import app.main as main_mod
    import app.storage as storage_mod
    for mod in (runs_mod, main_mod, upload_mod, storage_mod):  # these modules imported run_dir by name
        monkeypatch.setattr(mod, "run_dir", lambda rid: tmp_path / "runs" / rid)
    monkeypatch.setattr(upload_mod, "_pending_root", lambda: tmp_path / "pending")
    shas = {"sha": "a" * 64}

    async def fake_receive(video):
        shas["received"] = shas.get("received", 0) + 1
        p = tmp_path / f"{uuid4().hex}.mp4"
        p.write_bytes(b"x")
        return upload_mod.Received(p, "car.mp4", "mp4", 1, shas["sha"], 60.0)

    monkeypatch.setattr(upload_mod, "receive_upload", fake_receive)

    # hardening A7: runs from other tests stay "uploaded" in carlens_test; the server-wide run limit is not tested here
    real_config = upload_mod.get_config

    def config_without_run_limit():
        cfg = real_config().model_copy(deep=True)
        cfg.access.max_active_runs = 1_000_000
        return cfg
    monkeypatch.setattr(upload_mod, "get_config", config_without_run_limit)
    monkeypatch.setattr(main_mod, "get_config", config_without_run_limit)  # upload admission (hardening A2)
    from app.main import app
    return db_engine, app, shas, tmp_path


def _user_client(db_engine, app, tokens):
    from app.auth import hash_password
    from app.models import User
    email = f"t{uuid4().hex[:10]}@runs.test"
    with db_engine.begin() as conn:
        conn.execute(insert(User).values(email=email, password_hash=hash_password("user password 1"),
                                         role="user", status="approved", tokens=tokens))
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": email, "password": "user password 1"}, headers=ORIGIN).status_code == 200
    return client


def _finish(db_engine, run_id):
    from app.models import Run
    with db_engine.begin() as conn:
        conn.execute(update(Run).where(Run.id == run_id).values(status="partial"))


def _tokens(client):
    return client.get("/api/auth/me").json()["tokens"]


def test_one_token_per_run_and_one_run_at_a_time(env):
    db_engine, app, shas, _ = env
    client = _user_client(db_engine, app, tokens=2)
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
    alice = _user_client(db_engine, app, tokens=1)
    bob = _user_client(db_engine, app, tokens=1)
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
    client = _user_client(db_engine, app, tokens=3)
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
    other = _user_client(db_engine, app, tokens=1)
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
    client = _user_client(db_engine, app, tokens=2)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    other = _user_client(db_engine, app, tokens=1)
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


def test_user_cannot_restart_confirm(env, monkeypatch):  # hardening A1
    db_engine, app, shas, _ = env
    shas["sha"] = uuid4().hex * 2
    client = _user_client(db_engine, app, tokens=1)
    run_id = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    _finish(db_engine, run_id)
    assert client.post(f"/api/runs/{run_id}/confirm/start", headers=ORIGIN).status_code == 403

    import app.main as main_mod
    started = []
    monkeypatch.setattr(main_mod, "load_payload", lambda rid: {"odometer_found": False})
    monkeypatch.setattr(main_mod, "load_record", lambda rid: None)
    monkeypatch.setattr(main_mod, "is_paused", lambda rid: False)  # a payload but no graph waiting: the dev path
    monkeypatch.setattr(main_mod, "finish_confirm", lambda *a, **k: started.append("confirm"))
    monkeypatch.setattr(main_mod, "resume_from", lambda *a, **k: started.append("resume"))
    r = client.post(f"/api/runs/{run_id}/confirm", json={"car": {"make": "Maruti", "model": "Swift"}}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_waiting"
    assert started == []  # no paid step started


def test_resume_stops_after_the_free_resumes(env):  # hardening A7 (default free_resumes_per_run: 2)
    db_engine, app, shas, _ = env
    shas["sha"] = uuid4().hex * 2
    client = _user_client(db_engine, app, tokens=1)
    run_id = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    _finish(db_engine, run_id)
    from app.runs import append_event
    for _ in range(3):
        append_event(run_id, "pipeline", "run_done", {"status": "failed", "failed_at": "plan", "error": "test"})
    _finish(db_engine, run_id)
    r = client.post(f"/api/runs/{run_id}/resume", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "resume_limit"


def _audit_count(db_engine, action):
    from app.models import AuditLog
    from sqlalchemy import func
    with db_engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == action)).scalar_one()


def test_refused_upload_is_not_read_and_is_flagged(env):  # hardening A2
    db_engine, app, shas, _ = env
    client = _user_client(db_engine, app, tokens=0)
    before_reads, before_rows = shas.get("received", 0), _audit_count(db_engine, "upload_refused")
    r = client.post("/api/runs", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_tokens"
    assert shas.get("received", 0) == before_reads  # refused before the video was read
    assert _audit_count(db_engine, "upload_refused") == before_rows + 1


def test_same_video_again_keeps_no_copy(env):  # hardening A2 (owner, 20 Nov)
    db_engine, app, shas, tmp_path = env
    shas["sha"] = uuid4().hex * 2
    client = _user_client(db_engine, app, tokens=3)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    _finish(db_engine, run1)
    before = _audit_count(db_engine, "upload_same_video")

    first = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["pending_id"]
    again = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["pending_id"]
    assert again == first  # same note, timer refreshed
    kept = tmp_path / "pending" / first
    assert (kept / "pending.json").exists() and not list(kept.glob("video.*"))  # no second copy stored
    assert _audit_count(db_engine, "upload_same_video") == before + 2

    r = client.post(f"/api/uploads/{first}/start", headers=ORIGIN)  # fresh run copies the earlier video
    assert r.status_code == 200
    new_run = r.json()["run_id"]
    assert list((tmp_path / "runs" / new_run).glob("video.*"))
    assert list((tmp_path / "runs" / run1).glob("video.*"))  # the earlier run keeps its own


def test_failed_fresh_run_is_undone_and_can_be_retried(env, monkeypatch):  # fix 20 Nov
    """A fresh run that fails after its runs row exists leaves no half run: row gone, token back, kept upload back."""
    import app.nodes.upload as upload_mod
    from app.models import Run
    db_engine, app, shas, tmp_path = env
    shas["sha"] = uuid4().hex * 2
    client = _user_client(db_engine, app, tokens=3)
    run1 = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["run_id"]
    _finish(db_engine, run1)
    pending = client.post("/api/runs", files=VIDEO, headers=ORIGIN).json()["pending_id"]
    assert _tokens(client) == 2

    real_save = upload_mod.save_result

    def broken_save(*args, **kwargs):
        raise RuntimeError("database went away")
    monkeypatch.setattr(upload_mod, "save_result", broken_save)
    with pytest.raises(RuntimeError):
        client.post(f"/api/uploads/{pending}/start", headers=ORIGIN)
    assert _tokens(client) == 2  # token given back
    with db_engine.connect() as conn:
        user_runs = conn.execute(select(func.count()).select_from(Run).where(
            Run.video_sha256 == shas["sha"])).scalar_one()
    assert user_runs == 1  # only run1: the half run's row is gone
    assert (tmp_path / "pending" / pending / "pending.json").exists()  # kept upload put back

    monkeypatch.setattr(upload_mod, "save_result", real_save)
    r = client.post(f"/api/uploads/{pending}/start", headers=ORIGIN)
    assert r.status_code == 200 and _tokens(client) == 1
