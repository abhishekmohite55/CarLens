"""Sign-in plumbing (platform step 5, docs/platform/05-login.md): password hashing, authenticator codes,
sessions in the database, the session cookie, the Origin check and the route guards.

Pure helpers take plain values; only the guards and session functions touch the request or the database.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request, Response
from sqlalchemy import delete, insert, select

from .config import get_config
from .db import require_engine
from .models import Session, User

COOKIE = "carlens_session"
_hasher = PasswordHasher()
# Checked when the email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("not-a-real-password")
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Pages that depend on who is signed in: the browser must ask the server every time (no cached copy).
NO_STORE = {"Cache-Control": "no-store"}


class AuthError(Exception):
    """Answered as {"error": {"code", "message"}} like the other API errors (handler in main.py)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class SignedIn:
    id: int
    email: str
    role: str
    status: str
    tokens: int


# --- pure helpers ---

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(password_hash: str | None, password: str) -> bool:
    """argon2 check; a missing hash still costs one check (same timing as a wrong password)."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def code_matches(totp_secret: str | None, code: str | None) -> bool:
    """6-digit authenticator code; the code before and after the current 30 s window is also accepted (phone clock drift)."""
    if not totp_secret or not code:
        return False
    return pyotp.TOTP(totp_secret).verify(code.strip(), valid_window=1)


def key_hash(key: str) -> str:
    """Only this hash of the cookie value is stored, so a database leak gives no usable sessions."""
    return hashlib.sha256(key.encode()).hexdigest()


def origin_allowed(origin: str | None, referer: str | None, allowed: list[str]) -> bool:
    """CSRF check for changing requests: the Origin header (or, if absent, the Referer's origin) must be ours."""
    if not origin and referer:
        parts = urlsplit(referer)
        origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None
    return bool(origin) and origin.rstrip("/") in {a.rstrip("/") for a in allowed}


# --- sessions ---

def start_session(response: Response, user_id: int) -> None:
    """New session row + cookie. The cookie value is random; only its hash goes to the database."""
    cfg = get_config().auth
    key = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with require_engine().begin() as conn:
        conn.execute(delete(Session).where(Session.user_id == user_id, Session.expires_at <= now))
        conn.execute(insert(Session).values(key_hash=key_hash(key), user_id=user_id,
                                            expires_at=now + timedelta(hours=cfg.session_hours)))
    response.set_cookie(COOKIE, key, max_age=cfg.session_hours * 3600, httponly=True, secure=cfg.cookie_secure,
                        samesite="lax", path="/")


def end_session(request: Request, response: Response) -> None:
    key = request.cookies.get(COOKIE)
    if key:
        with require_engine().begin() as conn:
            conn.execute(delete(Session).where(Session.key_hash == key_hash(key)))
    response.delete_cookie(COOKIE, path="/")


def signed_in_user(request: Request) -> SignedIn | None:
    """The user behind the session cookie, or None (no cookie, unknown or expired session)."""
    key = request.cookies.get(COOKIE)
    if not key:
        return None
    now = datetime.now(timezone.utc)
    with require_engine().begin() as conn:
        row = conn.execute(
            select(User.id, User.email, User.role, User.status, User.tokens, Session.expires_at)
            .join(Session, Session.user_id == User.id).where(Session.key_hash == key_hash(key))).first()
        if row is None:
            return None
        if row.expires_at <= now:
            conn.execute(delete(Session).where(Session.key_hash == key_hash(key)))
            return None
    return SignedIn(row.id, row.email, row.role, row.status, row.tokens)


# --- route guards (FastAPI dependencies) ---

def check_origin(request: Request) -> None:
    if request.method in _UNSAFE and not origin_allowed(
            request.headers.get("origin"), request.headers.get("referer"), get_config().auth.allowed_origins):
        raise AuthError(403, "bad_origin", "Request from an unknown site.")


def require_user(request: Request) -> SignedIn:
    check_origin(request)
    user = signed_in_user(request)
    if user is None:
        raise AuthError(401, "not_signed_in", "Please sign in.")
    return user


def require_admin(request: Request) -> SignedIn:
    user = require_user(request)
    if user.role != "admin":
        raise AuthError(403, "admin_only", "Only the admin can use this.")
    return user
