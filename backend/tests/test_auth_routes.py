"""Admin sign-in through the API (platform stage 5.1); needs the carlens_test database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

ORIGIN = {"Origin": "http://127.0.0.1:8000"}


def _admin(db_engine, email):
    from app.auth import hash_password
    from app.models import User
    secret = pyotp.random_base32()
    with db_engine.begin() as conn:
        conn.execute(delete(User).where(User.email == email))
        conn.execute(insert(User).values(email=email, password_hash=hash_password("admin password 1"), role="admin",
                                         status="approved", tokens=0, totp_secret=secret))
    return secret


def test_admin_signs_in_with_password_and_code(db_engine):
    secret = _admin(db_engine, "admin-a@test")
    from app.main import app
    client = TestClient(app)

    assert client.get("/inspector", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={"email": "admin-a@test", "password": "admin password 1"}, headers=ORIGIN)
    assert r.json()["error"]["code"] == "code_required"

    r = client.post("/api/auth/login", headers=ORIGIN, json={
        "email": "Admin-A@test", "password": "admin password 1", "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert client.get("/api/auth/me").json()["email"] == "admin-a@test"
    page = client.get("/inspector", follow_redirects=False)
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 200

    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_tries_lock_the_email(db_engine):
    secret = _admin(db_engine, "admin-b@test")
    from app.main import app
    client = TestClient(app)
    for _ in range(4):
        r = client.post("/api/auth/login", json={"email": "admin-b@test", "password": "wrong password"}, headers=ORIGIN)
        assert r.json()["error"]["code"] == "wrong_login"
    r = client.post("/api/auth/login", headers=ORIGIN, json={
        "email": "admin-b@test", "password": "admin password 1", "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 429


def test_unknown_site_and_signed_out_are_refused(db_engine):
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": "x@test", "password": "y"}, headers={"Origin": "https://evil.example"})
    assert r.json()["error"]["code"] == "bad_origin"
    assert client.get("/api/config").status_code == 401
    assert client.get("/docs").status_code == 401
