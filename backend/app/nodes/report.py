"""Report node (PRC-5, PRC-6): reads what the earlier nodes saved, builds the report in Python (app/report.py,
no AI call) and saves report.json in the database. Missing price.json still gives a report with "valuation unavailable"."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from ..config import get_config
from ..report import build_report, inr
from ..results import load_result, save_result
from ..runs import append_event
from .confirm import load_record, load_verify_answer
from .photos import load_photos_answer

log = logging.getLogger(__name__)

_running: set[str] = set()
_running_lock = threading.Lock()


def try_claim(run_id: str) -> bool:
    with _running_lock:
        if run_id in _running:
            return False
        _running.add(run_id)
        return True


def run_report(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("report already running for %s", run_id)
        return
    try:
        _run_report_inner(run_id)
    except Exception as exc:
        log.exception("run_report failed for %s", run_id)
        append_event(run_id, "report", "node_failed", {"error": f"Unexpected error: {exc}"})
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_report_inner(run_id: str) -> None:
    confirm = load_record(run_id)
    if confirm is None:
        append_event(run_id, "report", "node_skipped", {"reason": "Confirm not done"})
        return
    append_event(run_id, "report", "node_started", {"label": "Building the report"})
    trimmed = load_result(run_id, "08_extract/trimmed.json") or {}
    report = build_report({
        "confirm": confirm,
        "verify": load_verify_answer(run_id),
        "manifest": load_result(run_id, "02_frames/manifest.json"),
        "locate_items": ((load_result(run_id, "01_locate/response.json") or {}).get("parsed") or {}).get("items"),
        "queries": load_result(run_id, "06_plan/queries.json"),
        "photos_answer": load_photos_answer(run_id),
        "price": load_result(run_id, "09_report/price.json"),
        "sources": {k: {"title": v.get("title"), "url": v.get("url")} for k, v in (trimmed.get("sources") or {}).items()},
        "km_min_confidence": get_config().photos.km_min_confidence,
    })
    report = {"run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **report}
    save_result(run_id, "09_report/report.json", report)
    p = report["price"]
    price = f"{inr(p['low'])} – {inr(p['high'])}" if p["status"] == "ok" else "valuation unavailable"
    append_event(run_id, "report", "node_done", {
        "summary": f"{price}; {len(report['damage'])} damage, {len(report['tyres'])} tyres, "
                   f"{len(report['repairs']['items'])} repair items",
        "files": ["09_report/report.json"]})
