"""pytest never touches the dev database (owner, 9 Nov 2026).

Runs before any test imports the app: DATABASE_URL is replaced by TEST_DATABASE_URL (database carlens_test),
or emptied when that is not set, so database writes are skipped.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
