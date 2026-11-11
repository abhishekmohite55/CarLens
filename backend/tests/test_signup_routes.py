"""Tester sign-up, Google sign-in and approval (platform stage 5.2); needs the carlens_test database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

ORIGIN = {"Origin": "http://127.0.0.1:8000"}


@pytest.fixture
def client(db_engine):
    from app.models import SignupAttempt, User
    with db_engine.begin() as conn:  # every test starts with no sign-up testers and no sign-up attempts
        conn.execute(delete(SignupAttempt))
        # testers of test_runs_tokens.py (@runs.test) own runs and stay
        conn.execute(delete(User).where(User.role == "tester", User.email.not_like("%@runs.test")))
    from app.main import app
    return TestClient(app)


def _signup(client, email, password="tester password 1"):
    return client.post("/api/auth/signup", json={"email": email, "password": password}, headers=ORIGIN)


def test_signup_is_a_pending_request_until_approved(client, db_engine):
    r = _signup(client, "Tester1@Gmail.com")
    assert r.status_code == 200 and r.json() == {"email": "tester1@gmail.com", "role": "tester", "status": "pending", "tokens": 0}
    assert client.get("/api/config").json()["error"]["code"] == "not_approved"
    assert client.post("/api/runs", headers=ORIGIN).status_code == 403  # upload: admin only until stage 5.3
    assert _signup(client, "tester1@gmail.com").json()["error"]["code"] == "email_taken"

    from app.models import User
    with db_engine.begin() as conn:
        conn.execute(update(User).where(User.email == "tester1@gmail.com").values(status="approved", tokens=5))
    assert client.get("/api/auth/me").json()["tokens"] == 5
    assert client.get("/api/config").status_code == 200


def test_signup_checks_email_password_and_limit(client):
    assert _signup(client, "not-an-email").json()["error"]["code"] == "bad_email"
    assert _signup(client, "short@gmail.com", "short").json()["error"]["code"] == "short_password"
    for i in range(5):
        assert _signup(client, f"many{i}@gmail.com").status_code == 200
    assert _signup(client, "many5@gmail.com").json()["error"]["code"] == "signup_limit"


def test_google_sign_in_creates_or_links_one_account(client, monkeypatch):
    import app.auth_routes as routes
    claims = {"sub": "g-123", "email": "tester2@gmail.com", "email_verified": True}
    monkeypatch.setattr(routes, "verify_google_token", lambda credential: claims)

    _signup(client, "tester2@gmail.com")  # same email with a password first
    client.post("/api/auth/logout", headers=ORIGIN)
    r = client.post("/api/auth/google", json={"credential": "x"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["status"] == "pending"

    claims.update(sub="g-456", email="tester3@gmail.com")  # new person: new pending account
    assert client.post("/api/auth/google", json={"credential": "x"}, headers=ORIGIN).json()["email"] == "tester3@gmail.com"


def test_google_refused_for_admin_and_unverified_email(client, db_engine, monkeypatch):
    from app.auth import hash_password
    from app.models import User
    with db_engine.begin() as conn:
        conn.execute(delete(User).where(User.email == "admin-g@test"))
        conn.execute(User.__table__.insert().values(email="admin-g@test", password_hash=hash_password("x" * 12),
                                                    role="admin", status="approved", tokens=0))
    import app.auth_routes as routes
    monkeypatch.setattr(routes, "verify_google_token",
                        lambda credential: {"sub": "g-admin", "email": "admin-g@test", "email_verified": True})
    assert client.post("/api/auth/google", json={"credential": "x"}, headers=ORIGIN).json()["error"]["code"] == "admin_password_only"

    monkeypatch.setattr(routes, "verify_google_token",
                        lambda credential: {"sub": "g-9", "email": "x@gmail.com", "email_verified": False})
    assert client.post("/api/auth/google", json={"credential": "x"}, headers=ORIGIN).json()["error"]["code"] == "bad_google_token"
