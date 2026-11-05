"""Plan node: listing queries from templates (Python) + part/tyre queries from the plan LLM chain, into 06_plan/."""
from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import PROJECT_ROOT, get_config
from ..llm.chat import ask_chain
from ..llm.tracing import langchain_callbacks
from ..plan import (build_user_prompt, car_problem, check_plan, damage_findings, listing_queries,
                    tyres_not_seen, tyres_to_judge)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate(parsed) -> str | None:
    return None if isinstance(parsed, dict) and isinstance(parsed.get("parts"), list) else "answer has no parts list"


def make_plan(confirm: dict, findings: list[dict], emit, callbacks: list, metadata: dict | None = None) -> dict:
    """Everything plan does without a run folder. Used by the node and scripts/check_plan.py.
    Returns {"request": dict | None, "response": dict | None, "queries": dict}; request/response are None when no LLM call."""
    cfg = get_config()
    seed = random.randrange(1_000_000)
    listing, empty = listing_queries(confirm.get("car") or {}, {"city": confirm.get("city"), "state": confirm.get("state")},
                                     cfg.plan.listing_templates, cfg.plan.listing_queries_per_run, random.Random(seed))
    damage = damage_findings(findings)
    tyres = tyres_to_judge(findings, cfg.plan.tyre_ok_score)
    new_price, _ = listing_queries(confirm.get("car") or {}, {"city": confirm.get("city"), "state": confirm.get("state")},
                                   cfg.plan.new_price_templates, cfg.plan.new_price_queries_per_run, random.Random(seed))
    queries = {"listing": listing, "new_price": new_price, "listing_seed": seed, "llm_called": bool(damage or tyres),
               "parts": [], "tyres": [], "tyres_not_seen": tyres_not_seen(findings), "problems": []}
    if len(listing) < cfg.plan.listing_queries_per_run:
        queries["problems"].append(f"{len(listing)} of {cfg.plan.listing_queries_per_run} listing queries"
                                   f" (empty fields: {', '.join(empty) or 'none'})")
    if not queries["llm_called"]:
        return {"request": None, "response": None, "queries": queries}

    prompts = PROJECT_ROOT / cfg.paths.prompts_dir
    system_prompt = (prompts / "plan_searches.system.md").read_text(encoding="utf-8")
    user_prompt = build_user_prompt((prompts / "plan_searches.user.md").read_text(encoding="utf-8"),
                                    confirm, damage, tyres, cfg.plan.queries_per_part)
    request = {"node": "plan", "chain": [{"provider": e.provider, "model": e.model} for e in cfg.models.plan_chain],
               "timeout_per_model_sec": cfg.models.plan_timeout_per_model_sec,
               "system_prompt": system_prompt, "user_prompt": user_prompt, "sent_at": _now()}
    answer = ask_chain(cfg.models.plan_chain,
                       lambda entry: [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
                       temperature=cfg.models.temperature, timeout_sec=cfg.models.plan_timeout_per_model_sec,
                       thinking_level=None, validate=_validate, emit=emit, callbacks=callbacks, metadata=metadata)
    response = {"received_at": _now(), **answer}
    if answer["parsed"] is None:
        queries["problems"].append("every plan model failed")
    else:
        plan, problems = check_plan(answer["parsed"], damage, tyres, cfg.plan.queries_per_part)
        queries.update(plan)
        queries["problems"] += problems
    return {"request": request, "response": response, "queries": queries}


def run_plan(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("plan already running for %s", run_id)
        return
    try:
        _run_plan_inner(run_id)
    except Exception as exc:
        log.exception("run_plan failed for %s", run_id)
        append_event(run_id, "plan", "node_failed", {"error": f"Unexpected error: {exc}"})
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_plan_inner(run_id: str) -> None:
    rd = run_dir(run_id)
    confirm_path = rd / "04_confirm.json"
    if not confirm_path.exists():
        append_event(run_id, "plan", "node_skipped", {"reason": "Confirm not done"})
        return
    append_event(run_id, "plan", "node_started", {"label": "Planning web searches"})
    confirm = json.loads(confirm_path.read_text(encoding="utf-8"))
    problem = car_problem(confirm.get("car") or {})
    if problem:
        append_event(run_id, "plan", "node_failed", {"error": problem})
        return

    findings = (json.loads((rd / "03_verify" / "response.json").read_text(encoding="utf-8")).get("parsed") or {}).get("findings") or []
    manifest_path = rd / "02_frames" / "manifest.json"
    if manifest_path.exists():  # locate category lets damage_findings tell a scratch from a badge
        categories = {i["item_id"]: i.get("category") for i in json.loads(manifest_path.read_text(encoding="utf-8"))["items"]}
        findings = [{**f, "category": categories.get(f.get("item_id"))} for f in findings]

    out = rd / "06_plan"
    out.mkdir(exist_ok=True)
    result = make_plan(confirm, findings,
                       emit=lambda msg: append_event(run_id, "plan", "node_progress", {"message": msg}),
                       callbacks=langchain_callbacks(run_id, "plan"),
                       metadata={"langfuse_session_id": run_id, "langfuse_trace_name": "plan"})
    files = []
    for name in ("request", "response", "queries"):
        if result[name] is not None:
            write_json_atomic(out / f"{name}.json", result[name])
            files.append(f"06_plan/{name}.json")

    q = result["queries"]
    if q["llm_called"] and result["response"]["parsed"] is None:
        append_event(run_id, "plan", "node_failed", {"error": "Every plan model failed", "files": files})
        return
    total = len(q["listing"]) + len(q.get("new_price") or []) + sum(len(p["queries"]) for p in q["parts"]) + sum(len(t["queries"]) for t in q["tyres"])
    who = result["response"]["answered_by"]["model"] if q["llm_called"] else "no LLM (no damage)"
    append_event(run_id, "plan", "packet", {"from": "plan", "to": "search", "label": f"{total} queries"})
    append_event(run_id, "plan", "node_done", {
        "summary": f"{total} queries ({len(q['listing'])} listing, {len(q.get('new_price') or [])} new price, {len(q['parts'])} parts, "
                   f"{len(q['tyres'])} tyres) by {who}; {len(q['problems'])} problems",
        "files": files})
