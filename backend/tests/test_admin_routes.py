"""Admin users, runs and audit API (platform stage 6.2); needs carlens_test.
Test users use the @runs.test domain, which the sign-up tests leave alone (they may own runs)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

ORIGIN = {"Origin": "http://127.0.0.1:8000"}


def _user(db_engine, role="tester", status="pending", tokens=0, password="tester password 1"):
    from app.auth import hash_password
    from app.models import User
    email = f"{role}{uuid4().hex[:10]}@runs.test"
    with db_engine.begin() as conn:
        return conn.execute(insert(User).values(email=email, password_hash=hash_password(password), role=role,
                                                status=status, tokens=tokens).returning(User.id)).scalar_one(), email


@pytest.fixture
def admin(db_engine, monkeypatch, tmp_path):
    from app.auth import SignedIn, require_admin
    from app.main import app
    import app.admin_routes as routes
    admin_id, email = _user(db_engine, role="admin", status="approved")
    app.dependency_overrides[require_admin] = lambda: SignedIn(admin_id, email, "admin", "approved", 0)
    monkeypatch.setattr(routes, "run_dir", lambda rid: tmp_path / rid)
    monkeypatch.setattr(routes, "forget_run", lambda rid: None)
    yield TestClient(app), admin_id, tmp_path
    app.dependency_overrides.clear()


def _audit(db_engine, admin_id):
    from app.models import AuditLog
    with db_engine.connect() as conn:
        return [r.action for r in conn.execute(select(AuditLog.action).where(AuditLog.admin_id == admin_id)
                                               .order_by(AuditLog.id))]


def test_approve_tokens_password_and_signout(admin, db_engine):
    client, admin_id, _ = admin
    user_id, email = _user(db_engine)
    pending = [u["email"] for u in client.get("/api/admin/users?status=pending").json()["users"]]
    assert email in pending

    assert client.post(f"/api/admin/users/{user_id}/approve", headers=ORIGIN).status_code == 200
    me = next(u for u in client.get("/api/admin/users").json()["users"] if u["id"] == user_id)
    assert (me["status"], me["tokens"]) == ("approved", 5)

    assert client.patch(f"/api/admin/users/{user_id}/tokens", json={"add": 3}, headers=ORIGIN).json()["tokens"] == 8
    assert client.patch(f"/api/admin/users/{user_id}/tokens", json={"add": -20}, headers=ORIGIN).json()["tokens"] == 0
    assert client.patch(f"/api/admin/users/{user_id}/tokens", json={"set": 2}, headers=ORIGIN).json()["tokens"] == 2

    r = client.post(f"/api/admin/users/{user_id}/password", json={"password": "short"}, headers=ORIGIN)
    assert r.json()["error"]["code"] == "short_password"
    assert client.post(f"/api/admin/users/{user_id}/password", json={"password": "new password 12"}, headers=ORIGIN).status_code == 200
    tester = TestClient(client.app)
    assert tester.post("/api/auth/login", json={"email": email, "password": "new password 12"}, headers=ORIGIN).status_code == 200
    assert client.post(f"/api/admin/users/{user_id}/signout", headers=ORIGIN).status_code == 200
    assert tester.get("/api/auth/me").status_code == 401

    assert _audit(db_engine, admin_id) == ["approve_user", "set_tokens", "set_tokens", "set_tokens", "reset_password", "sign_out_user"]
    actions = [e["action"] for e in client.get("/api/admin/audit").json()["entries"][:6]]
    assert actions[0] == "sign_out_user"


def test_admin_account_and_users_with_runs_are_protected(admin, db_engine):
    client, admin_id, _ = admin
    assert client.post(f"/api/admin/users/{admin_id}/reject", headers=ORIGIN).json()["error"]["code"] == "admin_account"

    from app.run_index import create_run_row
    user_id, _ = _user(db_engine, status="approved", tokens=1)
    create_run_row(sha256="d" * 64, original_filename="car.mp4", size_bytes=1, duration_sec=1.0, user_id=user_id)
    assert client.delete(f"/api/admin/users/{user_id}", headers=ORIGIN).json()["error"]["code"] == "has_runs"

    free_id, _ = _user(db_engine)
    assert client.delete(f"/api/admin/users/{free_id}", headers=ORIGIN).status_code == 200


def test_mark_failed_and_delete_run(admin, db_engine):
    client, _, tmp_path = admin
    from app.models import NodeRun, Run, RunEvent
    from app.run_index import create_run_row
    user_id, _ = _user(db_engine, status="approved", tokens=1)
    run_id = create_run_row(sha256="e" * 64, original_filename="car.mp4", size_bytes=1, duration_sec=1.0, user_id=user_id)
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "video.mp4").write_bytes(b"x")
    now = datetime.now(timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(update(Run).where(Run.id == run_id).values(status="running"))
        node = conn.execute(insert(NodeRun).values(run_id=run_id, node="locate", status="running", started_at=now)
                            .returning(NodeRun.id)).scalar_one()
        conn.execute(insert(RunEvent).values(run_id=run_id, seq=1, ts=now, node="locate", type="node_started", data={}))

    assert client.post(f"/api/admin/runs/{run_id}/fail", headers=ORIGIN).json()["error"]["code"] == "running_now"
    with db_engine.begin() as conn:
        conn.execute(update(NodeRun).where(NodeRun.id == node).values(status="done", finished_at=now))
    assert client.post(f"/api/admin/runs/{run_id}/fail", headers=ORIGIN).status_code == 200
    assert any(r["run_id"] == run_id and r["status"] == "failed" for r in client.get("/api/admin/runs").json()["runs"])
    assert client.get(f"/api/admin/runs/{run_id}").json()["steps"][0]["node"] == "locate"

    assert client.delete(f"/api/admin/runs/{run_id}", headers=ORIGIN).status_code == 200
    assert not (tmp_path / run_id).exists()
    with db_engine.connect() as conn:
        assert conn.execute(select(Run).where(Run.id == run_id)).first() is None
        assert conn.execute(select(RunEvent).where(RunEvent.run_id == run_id)).first() is None
    assert client.get(f"/api/admin/runs/{run_id}").status_code == 404
