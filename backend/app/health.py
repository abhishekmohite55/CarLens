"""Health (platform stage 9.3, docs/platform/09-cd.md §8): what the admin must know, in plain words.

    GET /api/health          public: {"status": "ok" | "degraded", "version"} (used by the deploy; no details)
    GET /api/admin/health    admin: the same plus every problem, the database version against the code, S3, maintenance
    python -m app.health --url http://127.0.0.1:8000/api/health --wait 90   (deploy: exit 0 when ok)

"degraded" = the database is not reachable, or the migration at startup failed / was not applied: new runs are
refused (maintenance.refuse_new_work). A database newer than the code (after a rollback) is only a warning.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from urllib.parse import urlsplit

from . import maintenance, startup, storage
from .db import database_url

_CACHE_SEC = 10
_cache: tuple[float, bool] | None = None


def _schema() -> dict:
    """Live: the database's migration against this code's newest one."""
    head, known = startup.code_revisions()
    url = database_url()
    if not url:
        return {"database": "none", "code_revision": head, "db_revision": None, "state": None, "error": None}
    try:
        db_rev = startup.db_revision(url)
    except Exception as exc:  # noqa: BLE001
        return {"database": "error", "code_revision": head, "db_revision": None, "state": None, "error": str(exc)[:300]}
    return {"database": "ok", "code_revision": head, "db_revision": db_rev,
            "state": startup.schema_state(db_rev, head, known), "error": None}


def _s3() -> dict:
    if not storage.enabled():
        return {"state": "off"}
    try:
        storage._s3().head_bucket(Bucket=storage.bucket())
        return {"state": "ok", "bucket": storage.bucket()}
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "bucket": storage.bucket(), "error": str(exc)[:300]}


def problems_from(report: dict, schema: dict, mstate: dict, s3: dict | None) -> list[dict]:
    """Plain-words problems, level "error" (degraded) or "warning". Pure: tested without a database."""
    out: list[dict] = []

    def add(level: str, message: str) -> None:
        out.append({"level": level, "message": message})

    if schema["database"] == "error":
        add("error", f"Database not reachable: {schema['error']}")
    elif schema["database"] == "none":
        add("error", "No database configured (DATABASE_URL is empty).")
    if report.get("migration") == "failed":
        add("error", f"{report.get('problem')} New runs are refused until it is fixed.")
    if schema["state"] == "behind":
        add("error", f"Database is at {schema['db_revision']}, this version needs {schema['code_revision']} "
                     "(migration not applied). New runs are refused.")
    elif schema["state"] == "ahead":
        add("warning", f"Database is at {schema['db_revision']}, newer than this version ({schema['code_revision']}): "
                       "an older version is running (rollback). Safe while migrations only add.")
    if report.get("config_problem"):
        add("warning", report["config_problem"])
    if mstate.get("on"):
        add("warning", f"Maintenance is on (since {mstate.get('since')}, by {mstate.get('by')}): no new runs.")
    elif mstate.get("expired"):
        add("warning", f"Maintenance was left on (since {mstate.get('since')}, by {mstate.get('by')}) and has been "
                       "ignored after maintenance.auto_off_min. Switch it off: python -m app.maintenance off")
    if s3 and s3.get("state") == "error":
        add("warning", f"S3 bucket {s3.get('bucket')} not reachable: {s3.get('error')}. Run files are not copied.")
    return out


def check(detail: bool = False) -> dict:
    report, schema, mstate = startup.read_report(), _schema(), maintenance.state()
    s3 = _s3() if detail else None
    problems = problems_from(report, schema, mstate, s3)
    result = {"status": "degraded" if any(p["level"] == "error" for p in problems) else "ok",
              "version": os.environ.get("CARLENS_GIT_COMMIT") or "unknown"}
    if detail:
        result.update(problems=problems, schema=schema, startup=report, s3=s3,
                      maintenance={**mstate, "since": mstate["since"].isoformat() if mstate.get("since") else None})
    return result


def is_degraded() -> bool:
    """Cached for a few seconds: routes ask on every new run."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < _CACHE_SEC:
        return _cache[1]
    try:
        degraded = check()["status"] == "degraded"
    except Exception:  # noqa: BLE001  health itself failing must not refuse runs
        degraded = False
    _cache = (time.monotonic(), degraded)
    return degraded


_LOCAL_HOSTS = ("127.0.0.1", "localhost")


def local_health_url(url: str) -> str:
    """The deploy's --url, only when it is this machine's /api/health; rebuilt here, so nothing else is fetched
    (hardening S4). Raises ValueError for any other address."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if (parts.scheme != "http" or parts.hostname not in _LOCAL_HOSTS or parts.path != "/api/health"
            or parts.query or parts.fragment or parts.username or parts.password or port is None or not 0 < port < 65536):
        raise ValueError("--url must be http://127.0.0.1:<port>/api/health (this machine only)")
    return f"http://127.0.0.1:{int(port)}/api/health"


def wait_until_ok(url: str, wait_sec: int) -> bool:
    """Deploy check: True once url answers {"status": "ok"}; prints what it sees."""
    deadline = time.monotonic() + wait_sec
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                answer = json.loads(response.read().decode("utf-8"))
            last = json.dumps(answer)
            if answer.get("status") == "ok":
                print(f"healthy: {last}")
                return True
        except Exception as exc:  # noqa: BLE001  server still starting
            last = str(exc)
        time.sleep(3)
    print(f"not healthy after {wait_sec} s: {last}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.health")
    parser.add_argument("--url", help="ask the server on this machine instead of checking here "
                                      "(only http://127.0.0.1:<port>/api/health)")
    parser.add_argument("--wait", type=int, default=0, help="with --url: keep asking this many seconds")
    args = parser.parse_args()
    if args.url:
        try:
            url = local_health_url(args.url)
        except ValueError as exc:
            print(exc)
            sys.exit(2)
        sys.exit(0 if wait_until_ok(url, max(args.wait, 1)) else 1)
    result = check(detail=True)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
