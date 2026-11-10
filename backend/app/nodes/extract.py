"""Extract node: trims 07_search results, asks the extract LLM chain to copy price text, then Python checks every
figure (in its snippet, rupees, limits, model + year, outliers). Writes 08_extract/."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import PROJECT_ROOT, get_config
from ..extract import car_line, check_figures, drop_outliers, group_summary, render_trimmed, trim_results
from ..llm.chat import ask_chain
from ..llm.tracing import langchain_callbacks
from ..photos import apply_photos
from ..results import load_result
from ..runs import append_event, run_dir, write_json_atomic
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
                 entries=None) -> dict:
    """Everything extract does without a run folder. Used by the node and scripts/check_extract.py.
    Returns {"request", "response", "figures"}; figures is None when every model failed."""
    cfg = get_config()
    entries = entries or cfg.models.extract_chain
    e = cfg.extract
    prompts = PROJECT_ROOT / cfg.paths.prompts_dir
    system_prompt = (prompts / "extract_prices.system.md").read_text(encoding="utf-8")
    user_prompt = (prompts / "extract_prices.user.md").read_text(encoding="utf-8").format(trimmed_text=text)
    request = {"node": "extract", "chain": [{"provider": m.provider, "model": m.model} for m in entries],
               "timeout_per_model_sec": cfg.models.extract_timeout_per_model_sec,
               "reasoning_effort": cfg.models.extract_reasoning_effort,
               "system_prompt": system_prompt, "user_prompt": user_prompt, "sent_at": _now()}
    answer = ask_chain(
        entries,
        lambda entry: [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        temperature=cfg.models.temperature, timeout_sec=cfg.models.extract_timeout_per_model_sec, thinking_level=None,
        validate=lambda p: None if isinstance(p, dict) and isinstance(p.get("figures"), list) else "no figures list",
        emit=emit, callbacks=callbacks, metadata=metadata, reasoning_effort=cfg.models.extract_reasoning_effort)
    response = {"received_at": _now(), **answer}
    if answer["parsed"] is None:
        return {"request": request, "response": response, "figures": None}

    limits = {"listing_min_inr": e.listing_min_inr, "listing_max_inr": e.listing_max_inr,
              "year_tolerance": cfg.pricing.year_tolerance, "outlier_factor": e.outlier_factor}
    kept, rejected = check_figures(answer["parsed"]["figures"], trimmed, car, limits)
    kept, outliers = drop_outliers(kept, e.outlier_factor)
    figures = {"answered_by": answer["answered_by"], "car": car, "summary": group_summary(kept),
               "kept": kept, "rejected": rejected, "outliers": outliers}
    return {"request": request, "response": response, "figures": figures}


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
    rd = run_dir(run_id)
    results_path = rd / "07_search" / "results.json"
    if not results_path.exists():
        append_event(run_id, "extract", "node_skipped", {"reason": "Search has no results"})
        return
    append_event(run_id, "extract", "node_started", {"label": "Reading prices from search results"})
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    confirm = load_result(run_id, "04_confirm.json")
    confirm = apply_photos(confirm, [], load_photos_answer(rd), get_config().photos.km_min_confidence)[0]  # photo km
    e = get_config().extract
    trimmed = trim_results(load(results_path), load(rd / "06_plan" / "queries.json"),
                           e.max_results_per_group, e.max_snippet_chars)
    text = render_trimmed(car_line(confirm), trimmed)
    trimmed["stats"]["chars_out"] = len(text)

    out = rd / "08_extract"
    out.mkdir(exist_ok=True)
    (out / "trimmed.txt").write_text(text, encoding="utf-8")
    write_json_atomic(out / "trimmed.json", trimmed)
    files = ["08_extract/trimmed.txt", "08_extract/trimmed.json"]
    emit = lambda msg: append_event(run_id, "extract", "node_progress", {"message": msg})
    emit(f"{len(text):,} chars to the extract model")

    result = make_extract(trimmed, text, confirm.get("car") or {}, emit=emit,
                          callbacks=langchain_callbacks(run_id, "extract"),
                          metadata={"langfuse_session_id": run_id, "langfuse_trace_name": "extract"})
    for name in ("request", "response", "figures"):
        if result[name] is not None:
            write_json_atomic(out / f"{name}.json", result[name])
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
