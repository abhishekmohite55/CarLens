"""Pricing node: Python-only price from the extract figures (database) (app/pricing.py rules) into 09_report/price.json."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from ..config import get_config
from ..pricing import price_report
from ..results import load_result
from ..runs import append_event, run_dir, write_json_atomic

log = logging.getLogger(__name__)

_running: set[str] = set()
_running_lock = threading.Lock()


def try_claim(run_id: str) -> bool:
    with _running_lock:
        if run_id in _running:
            return False
        _running.add(run_id)
        return True


def pricing_settings() -> dict:
    """The config.yaml `pricing:` values price_report needs. Shared with scripts/check_price.py."""
    p = get_config().pricing
    return {"min_listings_with_year": p.min_listings_with_year, "max_from_top": p.max_from_top,
            "min_listing_age": p.min_listing_age, "tyre_minor_wear_deduction_inr": p.tyre_minor_wear_deduction_inr}


def run_pricing(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("pricing already running for %s", run_id)
        return
    try:
        _run_pricing_inner(run_id)
    except Exception as exc:
        log.exception("run_pricing failed for %s", run_id)
        append_event(run_id, "pricing", "node_failed", {"error": f"Unexpected error: {exc}"})
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_pricing_inner(run_id: str) -> None:
    rd = run_dir(run_id)
    figs = load_result(run_id, "08_extract/figures.json")
    if figs is None:
        append_event(run_id, "pricing", "node_skipped", {"reason": "Extract has no figures"})
        return
    append_event(run_id, "pricing", "node_started", {"label": "Pricing the car"})
    queries = load_result(run_id, "06_plan/queries.json") or {}
    out = price_report(figs["kept"], queries.get("tyres") or [], figs["car"], datetime.now().year, pricing_settings())
    (rd / "09_report").mkdir(exist_ok=True)
    write_json_atomic(rd / "09_report" / "price.json", out)
    files = ["09_report/price.json"]
    if out["status"] != "ok":
        summary = f"Valuation unavailable: {out['reason']}"
    else:
        a = out["after_repairs"]
        summary = (f"\u20b9{a['median']:,} \u2013 \u20b9{a['max']:,} after \u20b9{out['repairs']['total']:,.0f} repairs "
                   f"({len(out['listings_used'])} listings)")
    append_event(run_id, "pricing", "node_done", {"summary": summary, "files": files})
