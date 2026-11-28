"""Extract node: trims 07_search results, asks the extract LLM chain to copy price text, then Python checks every
figure (in its snippet, rupees, limits, model + year, outliers). Saves trimmed.txt/.json, request, response, figures in the database.
Stage E1: a market with extract_mode "labels" has the LLM label every price too, and app/extract_rules.py keeps or
rejects it (no model-name check, no outlier rule)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import get_config, market_config, pinned
from ..settings_store import load_prompt
from ..extract import (PRICE_RE, USD_PRICE_RE, car_line, check_figures, drop_outliers, group_summary, parse_inr,
                       parse_usd, render_trimmed, trim_results)
from ..extract_rules import car_text, check_labelled
from ..llm.chat import ask_chain
from ..llm.tracing import langchain_callbacks
from ..photos import apply_photos
from ..results import load_result, save_result
from ..runs import append_event
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_extract(trimmed: dict, text: str, car: dict, emit, callbacks: list, metadata: dict | None = None,
                 entries=None, plan_queries: dict | None = None, mode: str | None = None) -> dict:
    """Everything extract does without a run folder. Used by the node and scripts/check_extract.py, check_judge.py.
    Returns {"request", "response", "figures"}; figures is None when every model failed.
    mode: "labels" | "classic"; default the market's extract_mode (stage E1). plan_queries: the plan's parts (labels
    mode reads each part's severity and action)."""
    cfg = get_config()
    entries = entries or cfg.models.extract_chain
    e = cfg.extract
    market = market_config()
    labels = (mode or market.extract_mode) == "labels"
    prefix = "extract_labels" if labels else "extract_prices"
    system_prompt = load_prompt(f"{prefix}.system.md")
    user_prompt = load_prompt(f"{prefix}.user.md").format(trimmed_text=text,
                                                          **({"car_text": car_text(car)} if labels else {}))
    request = {"node": "extract", "chain": [{"provider": m.provider, "model": m.model} for m in entries],
               "timeout_per_model_sec": cfg.models.extract_timeout_per_model_sec,
               "reasoning_effort": cfg.models.extract_reasoning_effort,
               "system_prompt": system_prompt, "user_prompt": user_prompt, "sent_at": _now()}
    answer = ask_chain(
        entries,
        lambda entry: [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        temperature=cfg.models.temperature, timeout_sec=cfg.models.extract_timeout_per_model_sec, thinking_level=None,
        validate=lambda p: None if isinstance(p, dict) and isinstance(p.get("figures"), list) else "no figures list",
        emit=emit, callbacks=callbacks, metadata=metadata, reasoning_effort=cfg.models.extract_reasoning_effort,
        max_in_flight=cfg.models.max_calls_in_flight)
    response = {"received_at": _now(), **answer}
    if answer["parsed"] is None:
        return {"request": request, "response": response, "figures": None}

    car_limits = market.extract_limits  # the run's market (stage M0); helper keys unchanged
    usd = market.currency == "USD"  # stage U5: dollars for US runs
    parse = parse_usd if usd else parse_inr
    if labels:  # stage E1: the LLM's labels + app/extract_rules.py, no outlier rule
        kept, rejected = check_labelled(answer["parsed"]["figures"], trimmed, plan_queries,
                                        (car_limits.listing_min, car_limits.listing_max),
                                        (market.light_repair_band.min, market.light_repair_band.max),
                                        parse, e.outlier_factor)
        outliers = []
    else:
        limits = {"listing_min_inr": car_limits.listing_min, "listing_max_inr": car_limits.listing_max,
                  "year_tolerance": cfg.pricing.year_tolerance, "outlier_factor": e.outlier_factor}
        kept, rejected = check_figures(answer["parsed"]["figures"], trimmed, car, limits, parse)
        kept, outliers = drop_outliers(kept, e.outlier_factor)
    figures = {"answered_by": answer["answered_by"], "car": car, "summary": group_summary(kept),
               "kept": kept, "rejected": rejected, "outliers": outliers,
               **({"mode": "labels"} if labels else {}),  # classic figures.json stays exactly as before E1
               **({"currency": "USD"} if usd else {})}  # US figures stay out of the shared price_figures table
    return {"request": request, "response": response, "figures": figures}


@pinned
def run_extract(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("extract already running for %s", run_id)
        return
    try:
        _run_extract_inner(run_id)
    except Exception as exc:
        log.exception("run_extract failed for %s", run_id)
        append_event(run_id, "extract", "node_failed", {"error": f"Unexpected error: {exc}"})
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_extract_inner(run_id: str) -> None:
    results = load_result(run_id, "07_search/results.json")
    if results is None:
        append_event(run_id, "extract", "node_skipped", {"reason": "Search has no results"})
        return
    append_event(run_id, "extract", "node_started", {"label": "Reading prices from search results"})
    confirm = load_result(run_id, "04_confirm.json")
    confirm = apply_photos(confirm, [], load_photos_answer(run_id), get_config().photos.km_min_confidence)[0]  # photo km
    e = get_config().extract
    usd = market_config().currency == "USD"  # stage U5: keep snippets with a $ amount for US runs
    plan_queries = load_result(run_id, "06_plan/queries.json")
    trimmed = trim_results(results, plan_queries,
                           e.max_results_per_group, e.max_snippet_chars, USD_PRICE_RE if usd else PRICE_RE)
    text = render_trimmed(car_line(confirm), trimmed)
    trimmed["stats"]["chars_out"] = len(text)

    save_result(run_id, "08_extract/trimmed.txt", text)  # saved before the call, so it exists even if every model fails
    save_result(run_id, "08_extract/trimmed.json", trimmed)
    files = ["08_extract/trimmed.txt", "08_extract/trimmed.json"]
    emit = lambda msg: append_event(run_id, "extract", "node_progress", {"message": msg})
    emit(f"{len(text):,} chars to the extract model")

    result = make_extract(trimmed, text, confirm.get("car") or {}, emit=emit,
                          callbacks=langchain_callbacks(run_id, "extract"),
                          metadata={"langfuse_session_id": run_id, "langfuse_trace_name": "extract"},
                          plan_queries=plan_queries)
    for name in ("request", "response", "figures"):
        if result[name] is not None:
            save_result(run_id, f"08_extract/{name}.json", result[name])  # figures.json also fills price_figures
            files.append(f"08_extract/{name}.json")

    f = result["figures"]
    if f is None:
        append_event(run_id, "extract", "node_failed", {"error": "Every extract model failed", "files": files})
        return
    who = f["answered_by"]["model"]
    secs = (result["response"]["attempts"] or [{}])[-1].get("seconds")
    append_event(run_id, "extract", "packet", {"from": "extract", "to": "pricing", "label": f"{len(f['kept'])} figures kept"})
    append_event(run_id, "extract", "node_done", {
        "summary": (f"{len(f['kept'])} figures kept, {len(f['rejected'])} rejected, {len(f['outliers'])} outliers "
                    f"by {who} in {secs} s"),
        "files": files})
