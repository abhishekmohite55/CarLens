"""Search node: runs every plan query (06_plan/queries.json, in the database) on Tavily, saves everything to 07_search/results.json."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tavily import TavilyClient

from ..config import get_config
from ..results import load_result
from ..runs import append_event, run_dir, write_json_atomic
from ..search import dedupe_urls, flatten_queries, search_totals

log = logging.getLogger(__name__)

_running: set[str] = set()
_running_lock = threading.Lock()

RESULT_KEYS = ("title", "url", "content", "score", "raw_content")


def try_claim(run_id: str) -> bool:
    with _running_lock:
        if run_id in _running:
            return False
        _running.add(run_id)
        return True


def search_all(items: list[dict], client: TavilyClient, emit=None) -> tuple[list[dict], float]:
    """Run items in parallel (search.workers). One failed query never stops the others. emit runs on this thread."""
    s = get_config().search

    def one(item: dict) -> dict:
        start = time.perf_counter()
        try:
            r = client.search(item["query"], search_depth=s.depth, max_results=s.max_results,
                              include_raw_content=s.include_raw_content,
                              include_domains=s.include_domains or None,
                              exclude_domains=s.exclude_domains or None, country=s.country)
            results = [{k: x.get(k) for k in RESULT_KEYS if k in x} for x in r.get("results") or []]
            return {**item, "seconds": round(time.perf_counter() - start, 2), "error": None, "results": results}
        except Exception as exc:
            return {**item, "seconds": round(time.perf_counter() - start, 2),
                    "error": f"{type(exc).__name__}: {exc}", "results": []}

    started = time.perf_counter()
    done: list[dict | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max(1, s.workers)) as pool:
        futures = {pool.submit(one, item): i for i, item in enumerate(items)}
        for n, fut in enumerate(as_completed(futures), start=1):
            done[futures[fut]] = fut.result()
            if emit:
                emit(f"{n}/{len(items)} queries done")
    return done, round(time.perf_counter() - started, 2)


def run_search(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("search already running for %s", run_id)
        return
    try:
        _run_search_inner(run_id)
    except Exception as exc:
        log.exception("run_search failed for %s", run_id)
        append_event(run_id, "search", "node_failed", {"error": f"Unexpected error: {exc}"})
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_search_inner(run_id: str) -> None:
    rd = run_dir(run_id)
    queries = load_result(run_id, "06_plan/queries.json")
    if queries is None:  # plan stopped before writing queries (e.g. make/model missing)
        append_event(run_id, "search", "node_skipped", {"reason": "Plan has no queries"})
        return
    items = flatten_queries(queries)
    if not items:
        append_event(run_id, "search", "node_skipped", {"reason": "No queries to search"})
        return
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        append_event(run_id, "search", "node_failed", {"error": "TAVILY_API_KEY not set in .env"})
        return

    append_event(run_id, "search", "node_started", {"label": f"Searching the web ({len(items)} queries)"})
    done, elapsed = search_all(items, TavilyClient(api_key=key),
                               emit=lambda msg: append_event(run_id, "search", "node_progress", {"message": msg}))
    urls = dedupe_urls(done)
    totals = search_totals(done, urls, get_config().search.depth, elapsed)
    out = rd / "07_search"
    out.mkdir(exist_ok=True)
    write_json_atomic(out / "results.json", {"settings": get_config().search.model_dump(), "queries": done,
                                             "urls": urls, "totals": totals})
    files = ["07_search/results.json"]

    if totals["failed"] == totals["queries"]:
        append_event(run_id, "search", "node_failed",
                     {"error": f"Every query failed: {done[0]['error']}", "files": files})
        return
    append_event(run_id, "search", "packet",
                 {"from": "search", "to": "extract", "label": f"{totals['results']} results, {totals['unique_urls']} URLs"})
    append_event(run_id, "search", "node_done", {
        "summary": (f"{totals['queries']} queries, {totals['failed']} failed, {totals['unique_urls']} URLs, "
                    f"~{totals['credits_estimate']} credits, {elapsed} s"),
        "files": files})
