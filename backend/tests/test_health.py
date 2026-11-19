"""Step 9.3: startup, health, new settings and the maintenance safety net, without a database."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.health import problems_from
from app.maintenance import expired
from app.settings_store import fill_defaults
from app.startup import code_revisions, schema_state

OK_SCHEMA = {"database": "ok", "code_revision": "0008_app_state", "db_revision": "0008_app_state", "state": "current",
             "error": None}
OFF = {"on": False, "since": None, "by": None, "expired": False}


def test_schema_state():
    known = {"0007_role_user", "0008_app_state"}
    assert schema_state("0008_app_state", "0008_app_state", known) == "current"
    assert schema_state(None, "0008_app_state", known) == "current"  # empty database: migrated next
    assert schema_state("0007_role_user", "0008_app_state", known) == "behind"
    assert schema_state("0009_future", "0008_app_state", known) == "ahead"  # rollback


def test_this_code_knows_its_migrations():
    head, known = code_revisions()
    assert head in known and "0001_rto" in known


def test_healthy_has_no_problems():
    assert problems_from({"migration": "ok"}, OK_SCHEMA, OFF, {"state": "ok"}) == []


def test_database_newer_is_only_a_warning():
    schema = {**OK_SCHEMA, "db_revision": "0009_future", "state": "ahead"}
    problems = problems_from({"migration": "skipped_db_ahead"}, schema, OFF, None)
    assert [p["level"] for p in problems] == ["warning"]
    assert "0009_future" in problems[0]["message"]


def test_failed_migration_and_unreachable_database_are_errors():
    failed = problems_from({"migration": "failed", "problem": "Migration failed at startup: boom."}, OK_SCHEMA, OFF, None)
    assert failed[0]["level"] == "error" and "boom" in failed[0]["message"]
    down = problems_from({}, {**OK_SCHEMA, "database": "error", "error": "timeout", "state": None}, OFF, None)
    assert down[0]["level"] == "error"


def test_maintenance_and_s3_are_warnings():
    on = {"on": True, "since": "2026-11-19T10:00:00+00:00", "by": "deploy abc1234", "expired": False}
    s3 = {"state": "error", "bucket": "b", "error": "denied"}
    assert [p["level"] for p in problems_from({"migration": "ok"}, OK_SCHEMA, on, s3)] == ["warning", "warning"]


def test_maintenance_expires():
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    assert not expired(now - timedelta(minutes=59), now, 60)
    assert expired(now - timedelta(minutes=60), now, 60)
    assert not expired(None, now, 60)


def test_fill_defaults_only_adds():
    active = {"auth": {"cookie_secure": True, "allowed_origins": ["https://x"]}, "dev": {"stop_after": ""}}
    defaults = {"auth": {"cookie_secure": False, "allowed_origins": [], "client_ip_header": ""},
                "dev": {"stop_after": "locate"}, "maintenance": {"confirm_grace_min": 5}}
    data, added = fill_defaults(active, defaults)
    assert data["auth"]["cookie_secure"] is True and data["auth"]["allowed_origins"] == ["https://x"]
    assert data["dev"]["stop_after"] == ""
    assert data["auth"]["client_ip_header"] == "" and data["maintenance"] == {"confirm_grace_min": 5}
    assert sorted(added) == ["auth.client_ip_header", "maintenance"]
    assert fill_defaults(data, defaults)[1] == []


def test_fill_defaults_stops_at_fields():
    data, added = fill_defaults({"models": {"verify_chain": [{"model": "a"}], "extra": {"k": 1}}},
                                {"models": {"verify_chain": [{"model": "b"}], "extra": {"k": 2, "new": 3}}})
    assert data["models"]["verify_chain"] == [{"model": "a"}]
    assert data["models"]["extra"] == {"k": 1}  # a field's own dict is the owner's value: not merged into
    assert added == []
