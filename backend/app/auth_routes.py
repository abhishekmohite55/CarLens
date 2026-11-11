"""Sign-in routes and the plain /login page (platform step 5, docs/platform/05-login.md §6, §7.1).
Stage 5.1: admin sign-in (password + authenticator code). Sign-up and Google come in 5.2.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .auth import NO_STORE, AuthError, SignedIn, check_origin, code_matches, end_session, password_matches, require_user, \
    start_session
from .config import get_config
from .users import find_user, is_locked, record_failed_login, record_login

router = APIRouter()
_LOGIN_PAGE = Path(__file__).parent / "login.html"
_WRONG = "Wrong email, password or code."


class LoginBody(BaseModel):
    email: str
    password: str
    code: str | None = None


@router.get("/login")
def login_page():
    return FileResponse(_LOGIN_PAGE, headers=NO_STORE)


@router.post("/api/auth/login", dependencies=[Depends(check_origin)])
def api_login(body: LoginBody, response: Response):
    cfg = get_config().auth
    user = find_user(body.email)
    if user is not None and is_locked(user.locked_until, datetime.now(timezone.utc)):
        raise AuthError(429, "locked", f"Too many wrong tries. Wait up to {cfg.lockout_minutes} minutes.")
    if not password_matches(user.password_hash if user else None, body.password) or user is None:
        if user is not None:
            record_failed_login(user.id, user.failed_logins, cfg.max_failed_logins, cfg.lockout_minutes)
        raise AuthError(401, "wrong_login", _WRONG)
    if user.role == "admin":
        if not body.code:
            raise AuthError(401, "code_required", "Enter the 6-digit code from your authenticator app.")
        if not code_matches(user.totp_secret, body.code):
            record_failed_login(user.id, user.failed_logins, cfg.max_failed_logins, cfg.lockout_minutes)
            raise AuthError(401, "wrong_login", _WRONG)
    record_login(user.id)
    start_session(response, user.id)
    return {"email": user.email, "role": user.role, "status": user.status, "tokens": user.tokens}


@router.post("/api/auth/logout", dependencies=[Depends(check_origin)])
def api_logout(request: Request, response: Response):
    end_session(request, response)
    return {"ok": True}


@router.get("/api/auth/me")
def api_me(user: SignedIn = Depends(require_user)):
    return {"email": user.email, "role": user.role, "status": user.status, "tokens": user.tokens}
