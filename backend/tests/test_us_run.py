"""US upload with VIN / state / miles, auto 04_confirm.json, no confirm pause (stage U2); needs carlens_test."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
VIDEO = {"video": ("car.mp4", b"x", "video/mp4")}
HONDA = "1HGCM82643A104332"
CAR = {"make": "HONDA", "model": "Accord", "variant": "EX-V6", "year": 2003, "fuel": "Gasoline", "body": "Coupe",
       "engine": "3.0L V6", "drive": None}


@pytest.fixture
def env(db_engine, tmp_path, monkeypatch):
    import app.main as main_mod
    import app.nodes.upload as upload_mod
    import app.runs as runs_mod
    import app.storage as storage_mod
    from app.auth import SignedIn, require_admin, require_approved
    from app.models import User, VinLookup
    for mod in (runs_mod, main_mod, upload_mod, storage_mod):
        monkeypatch.setattr(mod, "run_dir", lambda rid: tmp_path / "runs" / rid)
    monkeypatch.setattr(upload_mod, "_pending_root", lambda: tmp_path / "pending")
    reads = {"n": 0}

    async def fake_receive(video):
        reads["n"] += 1
        p = tmp_path / f"{uuid4().hex}.mp4"
        p.write_bytes(b"x")
        return upload_mod.Received(p, "car.mp4", "mp4", 1, uuid4().hex * 2, 60.0)
    monkeypatch.setattr(upload_mod, "receive_upload", fake_receive)
    real = main_mod.get_config

    def us_on():
        cfg = real().model_copy(deep=True)
        cfg.access.max_active_runs = 1_000_000
        cfg.dev.markets_on = {"in": True, "us": True}
        return cfg
    monkeypatch.setattr(main_mod, "get_config", us_on)
    monkeypatch.setattr(upload_mod, "get_config", us_on)
    with db_engine.begin() as conn:
        conn.execute(delete(VinLookup).where(VinLookup.vin == HONDA))
        admin_id = conn.execute(insert(User).values(email=f"a{uuid4().hex[:8]}@us.test", role="admin",
                                                    status="approved", tokens=0).returning(User.id)).scalar_one()
    signed = SignedIn(admin_id, "a@us.test", "admin", "approved", 0)
    main_mod.app.dependency_overrides[require_admin] = lambda: signed
    main_mod.app.dependency_overrides[require_approved] = lambda: signed
    yield db_engine, TestClient(main_mod.app), reads
    main_mod.app.dependency_overrides.clear()


def _found(db_engine):
    from app.models import VinLookup
    with db_engine.begin() as conn:
        conn.execute(insert(VinLookup).values(vin=HONDA, provider="vpic", ok=True, car=CAR, raw={"Results": []}, ms=5))


def test_us_upload_refused_before_reading(env):
    db_engine, client, reads = env
    r = client.post(f"/api/runs?market=us&vin={HONDA}&miles=48200", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "vin_lookup_missing"
    _found(db_engine)
    r = client.post(f"/api/runs?market=us&vin={HONDA}&miles=48.2k", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "miles_invalid"
    r = client.post(f"/api/runs?market=us&vin={HONDA}&miles=48200&state=ZZ", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "state_invalid"
    assert reads["n"] == 0  # nothing was read


def test_us_run_starts_with_the_vin_car_and_no_confirm_pause(env):
    from app.nodes.confirm import start_confirm
    from app.results import load_result
    from app.runs import read_events
    from app.settings_store import run_market
    db_engine, client, _ = env
    _found(db_engine)
    r = client.post(f"/api/runs?market=us&vin={HONDA.lower()}&miles=48,200&state=ca", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    assert run_market(run_id) == "us"
    meta = load_result(run_id, "meta.json")
    assert meta["vin"] == HONDA and meta["state_code"] == "CA" and meta["miles_user"] == 48200
    record = load_result(run_id, "04_confirm.json")
    assert record["car"]["model"] == "Accord" and record["state"] == "California" and record["source"] == "vin"
    assert load_result(run_id, "00_vin/response.json")["car"] == CAR
    assert start_confirm(run_id) is None  # never paused
    assert any(e["node"] == "confirm" and e["type"] == "node_skipped" for e in read_events(run_id))
    refused = client.post(f"/api/runs/{run_id}/confirm", json={"car": {"make": "HONDA", "model": "Accord"}},
                          headers=ORIGIN)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_for_us"


def test_india_upload_unchanged(env):
    from app.results import load_result
    _, client, _ = env
    r = client.post("/api/runs?market=in", files=VIDEO, headers=ORIGIN)
    assert r.status_code == 200
    meta = load_result(r.json()["run_id"], "meta.json")
    assert meta["market"] == "in" and "vin" not in meta
    assert load_result(r.json()["run_id"], "04_confirm.json") is None
