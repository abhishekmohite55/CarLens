"""Sign-in routes (platform step 5, docs/platform/05-login.md §6, §7.1).
5.1: admin sign-in (password + authenticator code). 5.2: user sign-up (password) and Google sign-in.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from .auth import AuthError, SignedIn, check_origin, code_matches, end_session, google_client_id, \
    hash_password, password_matches, require_user, start_session, verify_google_token
from .config import get_config
from .users import MIN_PASSWORD, create_user, find_google_user, find_user, is_locked, link_google, \
    looks_like_email, record_failed_login, record_login, signup_allowed, signups_last_hour

router = APIRouter()
_WRONG = "Wrong email, password or code."


class LoginBody(BaseModel):
    email: str
    password: str
    code: str | None = None


class SignupBody(BaseModel):
    email: str
    password: str


class GoogleBody(BaseModel):
    credential: str  # the ID token from Google's button


def _me(user) -> dict:
    return {"email": user.email, "role": user.role, "status": user.status, "tokens": user.tokens}


def _client_ip(request: Request) -> str:
    # Behind AWS's load balancer the real address comes from a header; decided in step 8 (05-login.md §10).
    return request.client.host if request.client else "unknown"


def _check_signup_limit(ip: str) -> None:
    if not signup_allowed(signups_last_hour(ip), get_config().auth.max_signups_per_hour):
        raise AuthError(429, "signup_limit", "Too many new accounts from this network. Try again in an hour.")


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
    return _me(user)


@router.post("/api/auth/signup", dependencies=[Depends(check_origin)])
def api_signup(body: SignupBody, request: Request, response: Response):
    """Sign-up = access request: a pending user, signed in at once so the page can show the status."""
    if not looks_like_email(body.email):
        raise AuthError(400, "bad_email", "Enter a valid email address.")
    if len(body.password) < MIN_PASSWORD:
        raise AuthError(400, "short_password", f"Use at least {MIN_PASSWORD} characters.")
    if find_user(body.email) is not None:
        raise AuthError(409, "email_taken", "This email already has an account. Sign in instead.")
    ip = _client_ip(request)
    _check_signup_limit(ip)
    user_id = create_user(body.email, ip, password_hash=hash_password(body.password))
    start_session(response, user_id)
    return _me(find_user(body.email))


@router.post("/api/auth/google", dependencies=[Depends(check_origin)])
def api_google(body: GoogleBody, request: Request, response: Response):
    """Google sign-in: Google proves the email; our rows decide everything else (pending, tokens, ...)."""
    try:
        claims = verify_google_token(body.credential)
    except ValueError:
        raise AuthError(401, "bad_google_token", "Google sign-in failed. Try again.")
    if not claims.get("email_verified") or not claims.get("email"):
        raise AuthError(401, "bad_google_token", "Google did not confirm this email.")
    sub, email = claims["sub"], claims["email"]

    user = find_google_user(sub) or find_user(email)
    if user is not None and user.role == "admin":
        raise AuthError(403, "admin_password_only", "The admin signs in with password and authenticator code.")
    if user is None:
        ip = _client_ip(request)
        _check_signup_limit(ip)
        create_user(email, ip, google_sub=sub)
    elif user.google_sub is None:
        link_google(user.id, sub)  # same email signed up with a password before: one account
    user = find_google_user(sub)
    record_login(user.id)
    start_session(response, user.id)
    return _me(user)


@router.post("/api/auth/logout", dependencies=[Depends(check_origin)])
def api_logout(request: Request, response: Response):
    end_session(request, response)
    return {"ok": True}


@router.get("/api/auth/google-client-id")
def api_google_client_id():
    """Public: the app's Google button needs it before anyone is signed in (empty = Google not set up)."""
    return {"client_id": google_client_id()}


@router.get("/api/auth/me")
def api_me(user: SignedIn = Depends(require_user)):
    return _me(user)
