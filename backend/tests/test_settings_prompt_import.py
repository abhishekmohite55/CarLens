"""(Runs after test_settings.py, which expects prompts still at version 1.) Import prompt files (owner, 28 Nov 2026): a new version only when the file differs; "Import all files" in one
click; the list marks prompts whose file differs. Needs carlens_test."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

ORIGIN = {"Origin": "http://127.0.0.1:8000"}
NAME = "verify.system.md"


@pytest.fixture
def admin(db_engine):
    from app.auth import SignedIn, hash_password, require_admin
    from app.main import app
    from app.models import User
    email = f"admin{uuid4().hex[:10]}@prompts.test"
    with db_engine.begin() as conn:
        admin_id = conn.execute(insert(User).values(email=email, password_hash=hash_password("x" * 12), role="admin",
                                                    status="approved", tokens=0).returning(User.id)).scalar_one()
    app.dependency_overrides[require_admin] = lambda: SignedIn(admin_id, email, "admin", "approved", 0)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _listed(admin, market="in"):
    return {p["name"]: p for p in admin.get(f"/api/admin/prompts?market={market}").json()["prompts"]}


def test_import_only_when_the_file_changed(admin):
    first = admin.post(f"/api/admin/prompts/{NAME}/import?market=in", headers=ORIGIN).json()
    again = admin.post(f"/api/admin/prompts/{NAME}/import?market=in", headers=ORIGIN).json()
    assert again["changed"] is False and again["version"] == first["version"]  # nothing new: no new version
    edited = admin.put(f"/api/admin/prompts/{NAME}?market=in", json={"text": "Edited in admin {x}", "note": "t"},
                       headers=ORIGIN)
    assert edited.status_code == 200 and _listed(admin)[NAME]["file_differs"] is True
    back = admin.post(f"/api/admin/prompts/{NAME}/import?market=in", headers=ORIGIN).json()
    assert back["changed"] is True and back["version"] == edited.json()["version"] + 1
    assert _listed(admin)[NAME]["file_differs"] is False


def test_import_all_files(admin):
    admin.put(f"/api/admin/prompts/{NAME}?market=us", json={"text": "US edit"}, headers=ORIGIN)
    r = admin.post("/api/admin/prompts/import-all?market=us", headers=ORIGIN).json()
    lines = {x["name"]: x for x in r["results"]}
    assert lines[NAME]["changed"] is True and lines[NAME]["to"] == lines[NAME]["from"] + 1
    assert r["changed"] == sum(1 for x in r["results"] if x["changed"]) and {x["market"] for x in r["results"]} == {"us"}
    again = admin.post("/api/admin/prompts/import-all?market=us", headers=ORIGIN).json()
    assert again["changed"] == 0  # second click: everything already up to date
    assert not any(p["file_differs"] for p in _listed(admin, "us").values())
