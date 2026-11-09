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


@pytest.fixture(scope="session")
def db_engine():
    """Engine on carlens_test with every table created; skips the test when TEST_DATABASE_URL is not set."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set (database carlens_test)")
    from app.db import get_engine
    from app.models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine
