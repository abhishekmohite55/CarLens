"""Config and prompt versions (platform stage 6.3): pure checks, then the admin API on carlens_test."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.config import CONFIG_PATH
from app.llm.chat import own_settings
from app.settings_store import check_config, check_prompt

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
NODES = ["locate", "frames", "verify", "confirm", "photos", "plan", "search", "extract", "pricing", "report"]


def _file_data() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _fields(problems):
    return {p["field"] for p in problems}


def test_config_yaml_passes_the_checks():
    checked, problems = check_config(_file_data(), NODES, "http://127.0.0.1:8000")
    assert problems == [] and checked["upload"]["max_duration_sec"] > 0


def test_bad_config_values_are_named():
    data = _file_data()
    data["dev"] = {"stop_after": "nowhere"}
    data["models"]["verify_chain"] = []
    data["models"]["plan_chain"][0] = {"provider": "someone", "model": " ", "timeout_sec": 0, "temperature": 3}
    data["upload"]["max_size_mb"] = "big"
    _, problems = check_config(data, NODES)
    assert _fields(problems) == {"upload.max_size_mb"}  # type errors first
    data["upload"]["max_size_mb"] = 0
    _, problems = check_config(data, NODES)
    assert {"dev.stop_after", "models.verify_chain", "models.plan_chain.0.provider", "models.plan_chain.0.model",
            "models.plan_chain.0.timeout_sec", "models.plan_chain.0.temperature", "upload.max_size_mb"} <= _fields(problems)


def test_own_origin_must_stay_allowed():
    data = _file_data()
    data["auth"]["allowed_origins"] = ["http://localhost:8000"]
    assert _fields(check_config(data, NODES, "http://127.0.0.1:5173")[1]) == {"auth.allowed_origins"}


def test_prompt_placeholders():
    assert check_prompt("verify.user.md", "Look at {frame_count} frames. JSON: {{\"a\": 1}}") == []
    assert check_prompt("verify.user.md", "Look at {frames}")[0]["message"].startswith("unknown placeholder")
    assert "unmatched" in check_prompt("verify.user.md", "broken { brace")[0]["message"]
    assert check_prompt("verify.system.md", "Any {braces} are fine here: not formatted") == []
    assert check_prompt("verify.system.md", "  ")[0]["message"] == "the prompt is empty"


def test_a_models_own_timeout_and_temperature_win():
    assert own_settings(SimpleNamespace(timeout_sec=None, temperature=None), 180, 0.2) == (180, 0.2)
    assert own_settings(SimpleNamespace(timeout_sec=60, temperature=0), 180, 0.2) == (60, 0)
    assert own_settings(SimpleNamespace(), 180, 0.2) == (180, 0.2)


@pytest.fixture
def admin(db_engine):
    from app.auth import SignedIn, hash_password, require_admin
    from app.main import app
    from app.models import User
    email = f"admin{uuid4().hex[:10]}@runs.test"
    with db_engine.begin() as conn:
        admin_id = conn.execute(insert(User).values(email=email, password_hash=hash_password("x" * 12), role="admin",
                                                    status="approved", tokens=0).returning(User.id)).scalar_one()
    app.dependency_overrides[require_admin] = lambda: SignedIn(admin_id, email, "admin", "approved", 0)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_config_versions_save_refuse_rollback_and_pin_runs(admin, db_engine):
    from app import settings_store
    from app.config import get_config, pinned_run
    from app.run_index import create_run_row

    first = admin.get("/api/admin/config").json()  # seeds version 1 from config.yaml on an empty table
    assert first["active"] and "locate" in first["options"]["stop_after"]
    old_run = create_run_row(sha256="f" * 64, original_filename="car.mp4", size_bytes=1, duration_sec=1.0)

    data = copy.deepcopy(first["data"])  # first["data"] stays the version-1 values to compare with
    data["dev"]["stop_after"] = "frames"
    data["models"]["verify_chain"][0]["timeout_sec"] = 45
    data["paths"]["runs_dir"] = "elsewhere"  # read-only: ignored
    saved = admin.put("/api/admin/config", json={"data": data, "note": "stop after frames"}, headers=ORIGIN)
    assert saved.status_code == 200 and saved.json()["version"] > first["id"]

    cfg = get_config()
    assert cfg.dev.stop_after == "frames" and cfg.models.verify_chain[0].timeout_sec == 45
    assert cfg.paths.runs_dir == first["data"]["paths"]["runs_dir"]
    with pinned_run(old_run):  # a run started before the save keeps its version
        assert get_config().dev.stop_after == first["data"]["dev"]["stop_after"]
    settings_store.repin_run(old_run)  # resume / dev re-run: the versions active now
    with pinned_run(old_run):
        assert get_config().dev.stop_after == "frames"

    data["dev"]["stop_after"] = "nowhere"
    refused = admin.put("/api/admin/config", json={"data": data}, headers=ORIGIN)
    assert refused.status_code == 422 and refused.json()["error"]["problems"][0]["field"] == "dev.stop_after"

    assert admin.post(f"/api/admin/config/rollback/{first['id']}", headers=ORIGIN).status_code == 200
    assert get_config().dev.stop_after == first["data"]["dev"]["stop_after"]
    notes = [v["note"] for v in admin.get("/api/admin/config/versions").json()["versions"]]
    assert notes[0] == f"rollback to v{first['id']}" and "stop after frames" in notes


def test_prompt_versions_and_pinned_runs(admin, db_engine):
    from app.config import pinned_run
    from app.run_index import create_run_row
    from app.settings_store import load_prompt

    names = [p["name"] for p in admin.get("/api/admin/prompts").json()["prompts"]]
    assert "verify.user.md" in names
    before = admin.get("/api/admin/prompts/verify.user.md").json()
    old_run = create_run_row(sha256="9" * 64, original_filename="car.mp4", size_bytes=1, duration_sec=1.0)

    bad = admin.put("/api/admin/prompts/verify.user.md", json={"text": "Check {nothing}"}, headers=ORIGIN)
    assert bad.status_code == 422
    new_text = before["text"] + "\nBe strict."
    saved = admin.put("/api/admin/prompts/verify.user.md", json={"text": new_text, "note": "strict"}, headers=ORIGIN)
    assert saved.status_code == 200 and saved.json()["version"] == before["number"] + 1 == 2

    assert load_prompt("verify.user.md") == new_text
    with pinned_run(old_run):
        assert load_prompt("verify.user.md") == before["text"]

    rolled = admin.post(f"/api/admin/prompts/verify.user.md/rollback/{before['id']}", headers=ORIGIN)
    assert rolled.status_code == 200 and rolled.json()["version"] == before["number"] + 2
    after = admin.get("/api/admin/prompts/verify.user.md").json()
    assert after["text"] == before["text"] and [v["number"] for v in after["versions"]] == [3, 2, 1]
    assert {p["number"] for p in admin.get("/api/admin/prompts").json()["prompts"] if p["name"] != "verify.user.md"} == {1}
