"""Pure sign-in helpers (platform stage 5.1): password hash, authenticator code, lockout, Origin check."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyotp

from app.auth import code_matches, hash_password, key_hash, origin_allowed, password_matches
from app.admin_data import new_tokens, step_status
from app.run_index import run_refusal
from app.users import after_failed_login, is_locked, looks_like_email, normal_email, signup_allowed

ALLOWED = ["http://127.0.0.1:8000", "http://localhost:8000"]


def test_password_hash_checks_and_hides_the_password():
    h = hash_password("long enough password")
    assert "long enough password" not in h
    assert password_matches(h, "long enough password")
    assert not password_matches(h, "wrong password")
    assert not password_matches(None, "anything")


def test_authenticator_code():
    secret = pyotp.random_base32()
    assert code_matches(secret, pyotp.TOTP(secret).now())
    assert not code_matches(secret, "abcdef")
    assert not code_matches(None, "123456")
    assert not code_matches(secret, None)


def test_lockout_after_the_limit_then_counter_resets():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    failed, locked = 0, None
    for _ in range(3):
        failed, locked = after_failed_login(failed, now, 4, 15)
        assert locked is None
    failed, locked = after_failed_login(failed, now, 4, 15)
    assert (failed, locked) == (0, now + timedelta(minutes=15))
    assert is_locked(locked, now + timedelta(minutes=14))
    assert not is_locked(locked, now + timedelta(minutes=15))
    assert not is_locked(None, now)


def test_origin_check():
    assert origin_allowed("http://127.0.0.1:8000", None, ALLOWED)
    assert not origin_allowed("https://evil.example", None, ALLOWED)
    assert origin_allowed(None, "http://localhost:8000/login", ALLOWED)
    assert not origin_allowed(None, None, ALLOWED)


def test_email_and_key_hash():
    assert normal_email("  Someone@Gmail.COM ") == "someone@gmail.com"
    assert key_hash("abc") == key_hash("abc") and key_hash("abc") != "abc"


def test_signup_email_shape_and_limit():
    assert looks_like_email("someone@gmail.com")
    assert not looks_like_email("someone")
    assert not looks_like_email("some one@gmail.com")
    assert not looks_like_email("a@b@gmail.com")
    assert not looks_like_email("someone@localhost")
    assert signup_allowed(4, 5) and not signup_allowed(5, 5)


def test_run_refusal_one_run_and_tokens():
    assert run_refusal(0, 1) is None
    assert run_refusal(1, 5).code == "run_in_progress"
    assert run_refusal(0, 0).code == "no_tokens"


def test_admin_token_change_never_below_zero():
    assert new_tokens(3, None, 2) == 5
    assert new_tokens(3, None, -10) == 0
    assert new_tokens(3, 7, None) == 7
    assert new_tokens(3, -1, None) == 0


def test_open_confirm_step_reads_as_awaiting_confirm():
    assert step_status("confirm", "running", None) == "awaiting_confirm"
    assert step_status("verify", "running", None) == "running"
    assert step_status("confirm", "done", None) == "done"
