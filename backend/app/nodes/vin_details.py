"""Vehicle details side job (stage U4, docs/backend/07-us-market.md §2.2 step 5b): for a US run, mcp.vin's recalls,
complaints, safety ratings and EPA fuel economy, fetched next to locate → frames → verify. Not a graph node (owner,
27 Nov: the graph's shape stays as it is, so India runs paused at confirm are safe): it starts with the run, plan waits
for it a little, and a failure never stops the run ("Recall and safety data not available")."""
from __future__ import annotations

import logging
import threading
import time

from ..config import current_market, get_config, pinned, pinned_run
from ..market import stop_after_for
from ..results import load_result, save_result
from ..runs import append_event
from ..vin.details import details_from, details_lines
from ..vin.providers import ProviderDown, provider_module

log = logging.getLogger(__name__)
NODE = "vin_details"
FILE = "00b_vin_details/response.json"
_running: set[str] = set()
_lock = threading.Lock()


def start_vin_details(run_id: str) -> None:
    """Start the job on its own thread when this is a US run that needs it (not done yet, not running, a details
    provider is set, the US stop is not "upload"). Returns at once."""
    with pinned_run(run_id):  # the run's own market and config version
        market, cfg = current_market(), get_config()
    if market != "us" or not cfg.vin.details_provider:
        return
    if stop_after_for("us", cfg.dev.stop_after, cfg.dev.stop_after_us) == "upload":
        return
    if load_result(run_id, FILE) is not None:
        return
    with _lock:
        if run_id in _running:
            return
        _running.add(run_id)
    threading.Thread(target=_run, args=(run_id,), daemon=True).start()


@pinned
def _run(run_id: str) -> None:
    try:
        vin_cfg = get_config().vin
        confirm = load_result(run_id, "04_confirm.json") or {}
        vin = confirm.get("vin")
        provider = vin_cfg.details_provider
        settings = vin_cfg.providers[provider]
        append_event(run_id, NODE, "node_started", {"label": "Vehicle details (recalls, safety, fuel economy)"})
        start = time.perf_counter()
        try:
            raw = provider_module(provider).decode(vin, settings)
        except ProviderDown as exc:
            _not_available(run_id, provider, f"{provider}: {exc}", round((time.perf_counter() - start) * 1000))
            return
        ms = round((time.perf_counter() - start) * 1000)
        details = details_from(raw, settings.fields, settings.recalls_path, vin_cfg.details_top_recalls)
        save_result(run_id, FILE, {"provider": provider, "vin": vin, "ms": ms, "details": details, "raw": raw})
        if not details["ok"]:
            append_event(run_id, NODE, "node_skipped", {"reason": "Recall and safety data not available (empty answer)"})
            return
        append_event(run_id, NODE, "packet", {"from": NODE, "to": "plan", "label": "recalls, safety"})
        append_event(run_id, NODE, "node_done", {"summary": "; ".join(details_lines(details)) or "details saved",
                                                 "files": [FILE]})
    except Exception as exc:  # noqa: BLE001  never stops the run
        log.exception("vin_details failed for %s", run_id)
        try:
            _not_available(run_id, "?", f"unexpected error: {exc}", None)
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _lock:
            _running.discard(run_id)


def _not_available(run_id: str, provider: str, why: str, ms: int | None) -> None:
    save_result(run_id, FILE, {"provider": provider, "ms": ms, "details": {"ok": False, "error": why}, "raw": None})
    append_event(run_id, NODE, "node_skipped", {"reason": f"Recall and safety data not available ({why})"})


def wait_for_details(run_id: str, timeout_sec: int, emit) -> dict | None:
    """Plan (US): the saved details, waiting at most timeout_sec while the job is still running; None when there are
    none (not started, failed or late)."""
    deadline = time.monotonic() + max(timeout_sec, 0)
    told = False
    while True:
        saved = load_result(run_id, FILE)
        if saved is not None:
            return saved.get("details") if (saved.get("details") or {}).get("ok") else None
        with _lock:
            running = run_id in _running
        if not running or time.monotonic() >= deadline:
            if running:
                emit(f"Vehicle details not ready after {timeout_sec} s: planning without them")
            return None
        if not told:
            emit("Waiting for vehicle details (recalls, safety)")
            told = True
        time.sleep(1)
