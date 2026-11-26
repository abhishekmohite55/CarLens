"""Markets on carlens_test (stage M0): run market, prompts per market, market off refuses uploads, admin filters."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
VIDEO = {"video": ("car.mp4", b"x", "video/mp4")}


@pytest.fixture
def env(db_engine, tmp_path, monkeypatch):
    import app.main as main_mod
    import app.nodes.upload as upload_mod
    import app.runs as runs_mod
    import app.storage as storage_mod
    for mod in (runs_mod, main_mod, upload_mod, storage_mod):  # these modules imported run_dir by name
        monkeypatch.setattr(mod, "run_dir", lambda rid: tmp_path / "runs" / rid)
    monkeypatch.setattr(upload_mod, "_pending_root", lambda: tmp_path / "pending")
    reads = {"n": 0}

    async def fake_receive(video):
        reads["n"] += 1
        p = tmp_path / f"{uuid4().hex}.mp4"
        p.write_bytes(b"x")
        return upload_mod.Received(p, "car.mp4", "mp4", 1, uuid4().hex * 2, 60.0)

    monkeypatch.setattr(upload_mod, "receive_upload", fake_receive)
    real_config = upload_mod.get_config

    def config_without_run_limit():
        cfg = real_config().model_copy(deep=True)
        cfg.access.max_active_runs = 1_000_000
        return cfg
    monkeypatch.setattr(upload_mod, "get_config", config_without_run_limit)
    monkeypatch.setattr(main_mod, "get_config", config_without_run_limit)
    from app.main import app
    return db_engine, app, reads


def _user(db_engine, tokens=1, market=None):
    from app.auth import hash_password
    from app.models import User
    email = f"m{uuid4().hex[:10]}@market.test"
    with db_engine.begin() as conn:
        user_id = conn.execute(insert(User).values(email=email, password_hash=hash_password("user password 1"),
                                                   role="user", status="approved", tokens=tokens, market=market)
                               .returning(User.id)).scalar_one()
    return user_id, email


def _login(app, email):
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": email, "password": "user password 1"},
                       headers=ORIGIN).status_code == 200
    return client


@pytest.fixture
def admin(db_engine):
    from app.auth import SignedIn, hash_password, require_admin, require_approved
    from app.main import app
    from app.models import User
    email = f"admin{uuid4().hex[:10]}@market.test"
    with db_engine.begin() as conn:
        admin_id = conn.execute(insert(User).values(email=email, password_hash=hash_password("x" * 12), role="admin",
                                                    status="approved", tokens=0).returning(User.id)).scalar_one()
    signed = SignedIn(admin_id, email, "admin", "approved", 0)
    app.dependency_overrides[require_admin] = lambda: signed
    app.dependency_overrides[require_approved] = lambda: signed
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_run_keeps_its_market_and_prompts_of_that_market(db_engine):
    from app import settings_store
    from app.run_index import create_run_row
    india = create_run_row(sha256="1" * 64, original_filename="a.mp4", size_bytes=1, duration_sec=1.0)
    us = create_run_row(sha256="2" * 64, original_filename="b.mp4", size_bytes=1, duration_sec=1.0, market="us")
    assert settings_store.run_market(india) == "in" and settings_store.run_market(us) == "us"
    assert "verify.user.md" in settings_store.active_prompt_ids("in")
    assert settings_store.active_prompt_ids("us") == {}  # prompts/us/ is empty in stage M0
    assert settings_store.pinned_ids(us)[1] is None


def test_prompts_listed_per_market(admin):
    india = admin.get("/api/admin/prompts?market=in").json()["prompts"]
    assert india and {p["market"] for p in india} == {"in"}
    assert admin.get("/api/admin/prompts?market=us").json()["prompts"] == []
    assert admin.get("/api/admin/prompts/verify.user.md?market=us").status_code == 422  # no US copy yet


def test_us_upload_refused_before_anything_is_read_or_spent(env):
    db_engine, app, reads = env
    _, email = _user(db_engine, tokens=1, market="us")
    client = _login(app, email)
    assert client.get("/api/config").json()["market"] == "us"
    before = reads["n"]
    r = client.post("/api/runs", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "market_off"
    assert reads["n"] == before and client.get("/api/auth/me").json()["tokens"] == 1


def test_users_cannot_pick_a_market(env):
    db_engine, app, _ = env
    _, email = _user(db_engine, tokens=1)
    client = _login(app, email)
    assert client.get("/api/config?market=us").json()["market"] == "in"  # the switch is the admin's only


def test_admin_switch_and_run_market(env, admin):
    db_engine, _, _ = env
    assert admin.get("/api/config?market=us").json()["market"] == "us"
    assert admin.post("/api/runs?market=us", files=VIDEO, headers=ORIGIN).json()["error"]["code"] == "market_off"
    r = admin.post("/api/runs?market=in", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 200
    runs = admin.get("/api/admin/runs?market=in").json()["runs"]
    assert any(x["run_id"] == r.json()["run_id"] and x["market"] == "in" for x in runs)
    assert all(x["market"] == "us" for x in admin.get("/api/admin/runs?market=us").json()["runs"])


def test_admin_pins_a_user_and_it_is_audited(db_engine, admin):
    from app.models import AuditLog
    user_id, email = _user(db_engine)
    r = admin.patch(f"/api/admin/users/{user_id}/market", json={"market": "us"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["market"] == "us"
    assert any(u["email"] == email for u in admin.get("/api/admin/users?market=us").json()["users"])
    assert not any(u["email"] == email for u in admin.get("/api/admin/users?market=in").json()["users"])
    with db_engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "set_market", AuditLog.target == f"user {user_id}")).scalar_one()
    assert n == 1
    entries = admin.get("/api/admin/audit?market=us").json()["entries"]
    assert any(e["action"] == "set_market" and e["target"] == f"user {user_id}" for e in entries)
    assert admin.patch(f"/api/admin/users/{user_id}/market", json={"market": "uk"}, headers=ORIGIN).status_code == 400
    assert admin.patch(f"/api/admin/users/{user_id}/market", json={"market": None}, headers=ORIGIN).json()["market"] is None


def test_dashboard_and_tables_take_the_market(admin):
    assert admin.get("/api/admin/dashboard?market=us").json()["problems"] == []
    tables = {t["name"]: t for t in admin.get("/api/admin/tables?market=us").json()["tables"]}
    assert tables["runs"]["market_split"] and not tables["rto_codes"]["market_split"]
    assert all(row["market"] == "us" for row in admin.get("/api/admin/tables/runs?market=us").json()["rows"])
