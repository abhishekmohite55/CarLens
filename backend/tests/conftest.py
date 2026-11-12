"""pytest never touches the dev database (owner, 9 Nov 2026).

Runs before any test imports the app: DATABASE_URL is replaced by TEST_DATABASE_URL (database carlens_test),
or emptied when that is not set, so database writes are skipped.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_tables():
    """Drop and recreate every table of carlens_test at the start of a test session (step 6.3): new columns and
    a config seeded from today's config.yaml, without rebuilding the database by hand. Test data only.
    Database not reachable: left alone (the app then reads config.yaml; DB tests fail on their own)."""
    if not os.environ.get("TEST_DATABASE_URL"):
        return
    from app.db import get_engine
    from app.models import Base

    engine = get_engine()
    if not (engine.url.database or "").endswith("_test"):  # never wipe a real database by a wrong .env line
        pytest.exit(f"TEST_DATABASE_URL must name a database ending in _test, not '{engine.url.database}'")
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    except Exception:  # noqa: BLE001  database not reachable
        pass


@pytest.fixture(scope="session")
def db_engine(_fresh_test_tables):
    """Engine on carlens_test with every table created; skips the test when TEST_DATABASE_URL is not set."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set (database carlens_test)")
    from app.db import get_engine

    return get_engine()
