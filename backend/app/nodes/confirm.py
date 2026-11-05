"""Confirm node: builds the pre-filled payload from verify, waits for the user, saves 04_confirm.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..config import PROJECT_ROOT, get_config
from ..confirm import build_payload, build_record, load_rto
from ..photos import list_photos
from ..runs import append_event, run_dir, write_json_atomic

PAYLOAD_FILE = "04_confirm_payload.json"
RECORD_FILE = "04_confirm.json"


def load_verify_answer(run_id: str) -> dict | None:
    path = run_dir(run_id) / "03_verify" / "response.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("parsed") if data.get("answered_by") else None


def start_confirm(run_id: str) -> dict | None:
    """Emit awaiting_confirm once and return the payload; None (node skipped) when verify has no answer."""
    rd = run_dir(run_id)
    payload_path = rd / PAYLOAD_FILE
    if payload_path.exists():  # graph resume re-runs the node: no second set of events
        return json.loads(payload_path.read_text(encoding="utf-8"))
    verify = load_verify_answer(run_id)
    if not verify:
        append_event(run_id, "confirm", "node_skipped", {"reason": "Verify has no answer"})
        return None
    cfg = get_config()
    payload = build_payload(verify, load_rto(PROJECT_ROOT / cfg.paths.rto_csv),
                            cfg.confirm.expand_below_confidence, cfg.confirm.year_range,
                            datetime.now().year)
    write_json_atomic(payload_path, payload)
    append_event(run_id, "confirm", "node_started", {"label": "Waiting for you to confirm the details"})
    append_event(run_id, "confirm", "awaiting_confirm", payload)
    return payload


def finish_confirm(run_id: str, payload: dict, answer: dict) -> dict:
    record = build_record(payload, answer, list_photos(run_dir(run_id) / "05_photos"))
    record["confirmed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_json_atomic(run_dir(run_id) / RECORD_FILE, record)
    car = record["car"]
    label = " ".join(str(car[k]) for k in ("make", "model", "year") if car.get(k)) or "car details"
    append_event(run_id, "confirm", "packet", {"from": "confirm", "to": "photos", "label": label})
    append_event(run_id, "confirm", "node_done", {
        "summary": f"Confirmed; changed: {', '.join(record['changed']) or 'nothing'}",
        "files": [RECORD_FILE],
    })
    return record

