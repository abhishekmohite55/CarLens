"""Pricing node: Python-only price from the extract figures (database) (app/pricing.py rules) saved as price.json in the database (also fills `prices`)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from ..config import get_config, market_config, pinned
from ..pricing import price_report
from .. import pricing_us  # owner 28 Nov: the US calculator is separate from India's
from ..results import load_result, save_result
from ..runs import append_event

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
    """The config.yaml `pricing:` values price_report needs (tyre deduction from the run's market, stage M0).
    Shared with scripts/check_price.py."""
    p = get_config().pricing
    return {"min_listings_with_year": p.min_listings_with_year, "max_from_top": p.max_from_top,
            "min_listing_age": p.min_listing_age,
            "tyre_minor_wear_deduction_inr": market_config().tyre_minor_wear_deduction}


@pinned
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


def _price_us(run_id: str, figs: dict, queries: dict) -> None:
    """Stage U5: US-wide price + state price (07-us-market.md §8), in USD, by app/pricing_us.py (original MSRP,
    repairs by action; owner 28 Nov); miles shown, not used yet (owner 27 Nov: decided after real US output)."""
    confirm = load_result(run_id, "04_confirm.json") or {}
    miles = load_result(run_id, "03_verify/miles.json") or {"miles_used": confirm.get("miles_user"), "source": "you"}
    p = get_config().pricing
    settings = {"min_listings_with_year": p.min_listings_with_year, "max_from_top": p.max_from_top,
                "min_listing_age": p.min_listing_age, "tyre_minor_wear_deduction": market_config().tyre_minor_wear_deduction}
    out = pricing_us.two_prices(figs["kept"], queries, figs["car"], datetime.now().year, settings, confirm.get("state"))
    out = {**out, "currency": "USD", "miles": {"used": miles.get("miles_used"), "source": miles.get("source"),
                                               "in_price": False, "note": "Miles are shown, not used in the price yet"}}
    save_result(run_id, "09_report/price.json", out)  # currency USD: not written to the shared prices table
    files = ["09_report/price.json"]
    if out["status"] != "ok":
        summary = f"US-wide: valuation unavailable: {out['reason']}"
    else:
        a = out["after_repairs"]
        summary = (f"US-wide ${a['median']:,} – ${a['max']:,} after ${out['repairs']['total']:,.0f} repairs "
                   f"({len(out['listings_used'])} listings)")
    st = out.get("state")
    if st:
        summary += (f"; {st['name']}: ${st['after_repairs']['median']:,} – ${st['after_repairs']['max']:,}"
                    if st["status"] == "ok" else f"; {st['reason']}")
    append_event(run_id, "pricing", "node_done", {"summary": summary, "files": files})


def _run_pricing_inner(run_id: str) -> None:
    figs = load_result(run_id, "08_extract/figures.json")
    if figs is None:
        append_event(run_id, "pricing", "node_skipped", {"reason": "Extract has no figures"})
        return
    append_event(run_id, "pricing", "node_started", {"label": "Pricing the car"})
    queries = load_result(run_id, "06_plan/queries.json") or {}
    if market_config().currency == "USD":
        _price_us(run_id, figs, queries)
        return
    out = price_report(figs["kept"], queries.get("tyres") or [], figs["car"], datetime.now().year, pricing_settings())
    save_result(run_id, "09_report/price.json", out)
    files = ["09_report/price.json"]
    if out["status"] != "ok":
        summary = f"Valuation unavailable: {out['reason']}"
    else:
        a = out["after_repairs"]
        summary = (f"\u20b9{a['median']:,} \u2013 \u20b9{a['max']:,} after \u20b9{out['repairs']['total']:,.0f} repairs "
                   f"({len(out['listings_used'])} listings)")
    append_event(run_id, "pricing", "node_done", {"summary": summary, "files": files})
