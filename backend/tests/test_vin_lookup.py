"""VIN lookup with saved answers, limits and errors (stage U1, app/vin/lookup.py + POST /api/vin/lookup).
vPIC is replaced by a fake: no network. Needs carlens_test."""
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from app.config import VinConfig, VinProviderConfig, VPIC_FIELDS

FIXTURES = Path(__file__).parent / "fixtures" / "vin"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
HONDA, BMW, TESLA = "1HGCM82643A104332", "WBA8E9C54JK542351", "5YJSA1E23HF013389"


def _cfg(**kw) -> VinConfig:
    return VinConfig(provider="vpic", providers={"vpic": VinProviderConfig(base_url="http://fake", fields=VPIC_FIELDS)},
                     **kw)


@pytest.fixture
def fake_vpic(db_engine, monkeypatch):
    from app.models import VinLookup
    from app.vin.providers import ProviderDown, vpic
    with db_engine.begin() as conn:
        conn.execute(delete(VinLookup))
    state = {"calls": 0, "down": False}

    def decode(vin, settings):
        state["calls"] += 1
        if state["down"]:
            raise ProviderDown("HTTP 503")
        return json.loads((FIXTURES / f"{vin}.vpic.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(vpic, "decode", decode)
    return state


def _user(db_engine):
    from app.models import User
    with db_engine.begin() as conn:
        return conn.execute(insert(User).values(email=f"v{uuid4().hex[:10]}@vin.test", role="user", status="approved",
                                                tokens=0).returning(User.id)).scalar_one()


def test_found_then_reused(db_engine, fake_vpic):
    from app.vin.lookup import lookup_vin
    user = _user(db_engine)
    first = lookup_vin(" 1hgcm82643a104332 ", user, _cfg())
    assert first["ok"] and first["car"]["model"] == "Accord" and not first["reused"] and fake_vpic["calls"] == 1
    again = lookup_vin(HONDA, user, _cfg())
    assert again["reused"] and again["car"] == first["car"] and fake_vpic["calls"] == 1


def test_invalid_vin_never_calls(db_engine, fake_vpic):
    from app.vin.lookup import VinError, lookup_vin
    with pytest.raises(VinError) as e:
        lookup_vin("1HGCM82653A104332", _user(db_engine), _cfg())
    assert e.value.status == 422 and e.value.code == "vin_invalid" and fake_vpic["calls"] == 0


def test_not_found_is_a_clear_message_and_is_saved(db_engine, fake_vpic):
    from app.vin.lookup import VinError, lookup_vin
    user = _user(db_engine)
    for _ in range(2):
        with pytest.raises(VinError) as e:
            lookup_vin(BMW, user, _cfg())
        assert e.value.status == 422 and e.value.code == "vin_not_found" and "BMW" in e.value.message
    assert fake_vpic["calls"] == 1  # the second time: the saved answer


def test_provider_down_says_come_back_later_and_is_not_reused(db_engine, fake_vpic):
    from app.vin.lookup import UNAVAILABLE, VinError, lookup_vin
    user = _user(db_engine)
    fake_vpic["down"] = True
    with pytest.raises(VinError) as e:
        lookup_vin(TESLA, user, _cfg())
    assert e.value.status == 503 and e.value.message == UNAVAILABLE
    fake_vpic["down"] = False
    assert lookup_vin(TESLA, user, _cfg())["ok"] and fake_vpic["calls"] == 2


def test_rate_limit_counts_real_calls_only(db_engine, fake_vpic):
    from app.vin.lookup import VinError, lookup_vin
    user = _user(db_engine)
    lookup_vin(HONDA, user, _cfg(max_lookups_per_hour=1))
    lookup_vin(HONDA, user, _cfg(max_lookups_per_hour=1))  # saved answer: not counted
    with pytest.raises(VinError) as e:
        lookup_vin(TESLA, user, _cfg(max_lookups_per_hour=1))
    assert e.value.status == 429 and e.value.code == "too_many"
    assert lookup_vin(TESLA, user, _cfg(max_lookups_per_hour=1), is_admin=True)["ok"]  # the admin has no limit


def test_route_refused_while_us_is_off_then_answers(db_engine, fake_vpic, monkeypatch):
    import app.main as main_mod
    from app.auth import SignedIn, require_approved
    from app.main import app
    user = _user(db_engine)
    app.dependency_overrides[require_approved] = lambda: SignedIn(user, "v@vin.test", "user", "approved", 0)
    try:
        client = TestClient(app)
        off = client.post("/api/vin/lookup", json={"vin": HONDA}, headers=ORIGIN)
        assert off.status_code == 409 and off.json()["error"]["code"] == "market_off" and fake_vpic["calls"] == 0

        real = main_mod.get_config

        def us_on():
            cfg = real().model_copy(deep=True)
            cfg.dev.markets_on = {"in": True, "us": True}
            cfg.vin = _cfg()
            return cfg
        monkeypatch.setattr(main_mod, "get_config", us_on)
        ok = client.post("/api/vin/lookup", json={"vin": HONDA}, headers=ORIGIN)
        assert ok.status_code == 200 and ok.json()["car"]["make"] == "HONDA"
        bad = client.post("/api/vin/lookup", json={"vin": "1HGCM8264"}, headers=ORIGIN)
        assert bad.status_code == 422 and bad.json()["error"]["message"] == "A VIN has 17 characters (you typed 9)."
        cfg = client.get("/api/config").json()["us"]
        assert "CA" in cfg["top_states"] and len(cfg["states"]) == 51 and cfg["state_guess"] is None
    finally:
        app.dependency_overrides.clear()
