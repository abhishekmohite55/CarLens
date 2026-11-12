"""Admin dashboard and table browser (platform stage 6.4); needs carlens_test."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert


@pytest.fixture
def admin(db_engine):
    from app.auth import SignedIn, hash_password, require_admin
    from app.main import app
    from app.models import User
    email = f"admin{uuid4().hex[:10]}@runs.test"
    with db_engine.begin() as conn:
        admin_id = conn.execute(insert(User).values(email=email, password_hash=hash_password("x" * 12), role="admin",
                                                    status="approved", tokens=0, totp_secret="SECRET")
                                .returning(User.id)).scalar_one()
    app.dependency_overrides[require_admin] = lambda: SignedIn(admin_id, email, "admin", "approved", 0)
    yield TestClient(app), email
    app.dependency_overrides.clear()


def test_tables_are_listed_and_secrets_masked(admin):
    client, email = admin
    names = {t["name"] for t in client.get("/api/admin/tables").json()["tables"]}
    assert {"users", "runs", "audit_log", "config_versions"} <= names

    page = client.get("/api/admin/tables/users", params={"search": email}).json()
    assert page["total"] == 1
    row = page["rows"][0]
    assert row["email"] == email and row["password_hash"] == "•••" and row["totp_secret"] == "•••"

    assert client.get("/api/admin/tables/users", params={"column": "password_hash", "value": "a"}).status_code == 400
    assert client.get("/api/admin/tables/users", params={"sort": "nope"}).status_code == 400
    assert client.get("/api/admin/tables/pg_user").status_code == 404
    assert client.get("/api/admin/tables/users", params={"column": "role", "value": "admin"}).json()["total"] >= 1


def test_dashboard_answers(admin):
    client, _ = admin
    d = client.get("/api/admin/dashboard", params={"days": 7}).json()
    assert d["days"] == 7
    for key in ("runs_per_day", "steps", "last_errors", "models", "tavily", "access", "tokens", "prices", "in_progress"):
        assert key in d
    assert d["tavily"]["free_credits"] == 1000 and d["access"]["pending"] >= 0
