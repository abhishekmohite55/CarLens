"""Container start (platform stage 9.3, docs/platform/09-cd.md §8): migrate the database and add new config settings,
but never keep the server from starting. Run by docker-entrypoint.sh before uvicorn:

    python -m app.startup

- Database newer than this code (a rollback): no migration, start, warn (safe while migrations only add).
- Migration fails (or no database): start anyway; health reports "degraded" and new runs are refused.
- New config settings this code knows and the active config version lacks: saved as a new version that only adds
  them, with their config.yaml values (never changes a value already set).
What happened is written to STARTUP_FILE (one JSON object) for app/health.py.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from .db import database_url

STARTUP_FILE = Path(os.environ.get("CARLENS_STARTUP_FILE", "/tmp/carlens-startup.json"))
BACKEND_DIR = Path(__file__).parent.parent


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def code_revisions() -> tuple[str, set[str]]:
    """(newest migration this code has, every migration this code has)."""
    script = ScriptDirectory.from_config(alembic_config())
    return script.get_current_head(), {s.revision for s in script.walk_revisions()}


def db_revision(url: str) -> str | None:
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def schema_state(db_rev: str | None, head: str, known: set[str]) -> str:
    """current: up to date (or empty, migrated next) · ahead: database newer than this code · behind: migration due."""
    if db_rev is None or db_rev == head:
        return "current"
    return "behind" if db_rev in known else "ahead"


def migrate() -> dict:
    head, known = code_revisions()
    report = {"at": datetime.now(timezone.utc).isoformat(), "code_revision": head, "db_revision": None,
              "migration": "ok", "problem": None}
    url = database_url()
    if not url:
        report.update(migration="no_database", problem="DATABASE_URL is not set: started without a database.")
        return report
    try:
        db_rev = db_revision(url)
        report["db_revision"] = db_rev
        if schema_state(db_rev, head, known) == "ahead":
            report.update(migration="skipped_db_ahead",
                          problem=f"Database is at {db_rev}; this version knows up to {head}. Started without "
                                  "migrating (safe while migrations only add tables and columns).")
            return report
        command.upgrade(alembic_config(), "head")
        report["db_revision"] = head
    except Exception as exc:  # noqa: BLE001  the server must start anyway (degraded)
        report.update(migration="failed", problem=f"Migration failed at startup: {exc}"[:600])
    return report


def add_new_settings(report: dict) -> None:
    if report["migration"] not in ("ok", "skipped_db_ahead"):
        return
    try:
        from .graph import ORDER  # imported here: heavy (LangGraph), and only needed for the config check
        from .settings_store import add_missing_settings
        report["config"] = add_missing_settings(list(ORDER))
    except Exception as exc:  # noqa: BLE001
        report["config_problem"] = f"New config settings were not added: {exc}"[:600]


def read_report() -> dict:
    try:
        return json.loads(STARTUP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> None:
    report = migrate()
    add_new_settings(report)
    try:
        STARTUP_FILE.write_text(json.dumps(report), encoding="utf-8")
    except OSError as exc:
        print(f"startup report not written: {exc}")
    print(f"startup: migration {report['migration']}"
          + (f" - {report['problem']}" if report.get("problem") else "")
          + (f"; config: {report['config']}" if report.get("config") else "")
          + (f"; {report['config_problem']}" if report.get("config_problem") else ""), flush=True)


if __name__ == "__main__":
    main()  # always exits 0: uvicorn starts next, whatever happened
