"""User rows and the owner's commands (platform step 5, docs/platform/05-login.md §7.4).

    python -m app.users create-admin you@example.com    asks the password twice, prints the authenticator setup key
    python -m app.users set-password someone@gmail.com  owner resets a forgotten password
"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import func, insert, select, update

from .auth import hash_password
from .db import require_engine
from .models import SignupAttempt, User

MIN_PASSWORD = 10


def normal_email(email: str) -> str:
    return email.strip().lower()


def after_failed_login(failed: int, now: datetime, max_failed: int, lockout_minutes: int) -> tuple[int, datetime | None]:
    """New (failed_logins, locked_until) after one more wrong password or code. At the limit: locked, counter reset."""
    failed += 1
    if failed >= max_failed:
        return 0, now + timedelta(minutes=lockout_minutes)
    return failed, None


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def looks_like_email(email: str) -> bool:
    """Light shape check only (no verification email, owner decision): one @, a dot in the domain, no spaces."""
    email = normal_email(email)
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain.strip(".") and " " not in email and email.count("@") == 1


def signup_allowed(recent_signups: int, max_per_hour: int) -> bool:
    return recent_signups < max_per_hour


def find_user(email: str):
    with require_engine().connect() as conn:
        return conn.execute(select(User).where(User.email == normal_email(email))).first()


def find_google_user(google_sub: str):
    with require_engine().connect() as conn:
        return conn.execute(select(User).where(User.google_sub == google_sub)).first()


def signups_last_hour(ip: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    with require_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(SignupAttempt)
                            .where(SignupAttempt.ip == ip, SignupAttempt.created_at > since)).scalar_one()


def create_tester(email: str, ip: str, password_hash: str | None = None, google_sub: str | None = None) -> int:
    """New pending tester (= an access request) and one sign-up attempt for the address, in one transaction."""
    with require_engine().begin() as conn:
        user_id = conn.execute(insert(User).values(
            email=normal_email(email), password_hash=password_hash, google_sub=google_sub, role="tester",
            status="pending", tokens=0).returning(User.id)).scalar_one()
        conn.execute(insert(SignupAttempt).values(ip=ip))
    return user_id


def link_google(user_id: int, google_sub: str) -> None:
    with require_engine().begin() as conn:
        conn.execute(update(User).where(User.id == user_id).values(google_sub=google_sub))


def record_failed_login(user_id: int, failed: int, max_failed: int, lockout_minutes: int) -> None:
    failed, locked_until = after_failed_login(failed, datetime.now(timezone.utc), max_failed, lockout_minutes)
    with require_engine().begin() as conn:
        conn.execute(update(User).where(User.id == user_id).values(failed_logins=failed, locked_until=locked_until))


def record_login(user_id: int) -> None:
    with require_engine().begin() as conn:
        conn.execute(update(User).where(User.id == user_id).values(
            failed_logins=0, locked_until=None, last_login_at=datetime.now(timezone.utc)))


# --- commands ---

def _ask_password() -> str:
    first = getpass.getpass("Password (min %d characters): " % MIN_PASSWORD)
    if len(first) < MIN_PASSWORD:
        sys.exit("Too short.")
    if getpass.getpass("Same password again: ") != first:
        sys.exit("The two passwords differ.")
    return first


def create_admin(email: str) -> None:
    email = normal_email(email)
    if find_user(email):
        sys.exit(f"{email} already exists.")
    password = _ask_password()
    secret = pyotp.random_base32()
    with require_engine().begin() as conn:
        conn.execute(insert(User).values(email=email, password_hash=hash_password(password), role="admin",
                                         status="approved", tokens=0, totp_secret=secret,
                                         approved_at=datetime.now(timezone.utc)))
    print(f"Admin {email} created.")
    print("Authenticator app: add an account with a setup key (time based):")
    print(f"  account: CarLens ({email})")
    print(f"  key:     {secret}")
    print("Keep the key private; it is shown only now.")


def set_password(email: str) -> None:
    user = find_user(email)
    if user is None:
        sys.exit(f"No user {normal_email(email)}.")
    password = _ask_password()
    with require_engine().begin() as conn:
        conn.execute(update(User).where(User.id == user.id).values(
            password_hash=hash_password(password), failed_logins=0, locked_until=None))
    print(f"Password of {user.email} changed.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.users")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin").add_argument("email")
    sub.add_parser("set-password").add_argument("email")
    args = parser.parse_args()
    {"create-admin": create_admin, "set-password": set_password}[args.command](args.email)


if __name__ == "__main__":
    main()
