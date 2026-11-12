"""Confirm node: builds the pre-filled payload from verify, waits for the user, saves 04_confirm.json."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..config import get_config, pinned
from ..confirm import build_payload, build_record
from ..db import require_engine
from ..models import RtoCode, State
from ..photos import list_photos
from ..results import load_result, save_result
from ..runs import append_event, run_dir

PAYLOAD_FILE = "04_confirm_payload.json"
RECORD_FILE = "04_confirm.json"


def load_verify_answer(run_id: str) -> dict | None:
    data = load_result(run_id, "03_verify/response.json")
    if data is None:
        return None
    return data.get("parsed") if data.get("answered_by") else None


def load_payload(run_id: str) -> dict | None:
    """The pre-filled form, or None when confirm has not started."""
    return load_result(run_id, PAYLOAD_FILE)


def load_record(run_id: str) -> dict | None:
    """The confirmed values (04_confirm.json), or None when the user has not confirmed."""
    return load_result(run_id, RECORD_FILE)


def rto_rows() -> list[dict]:
    """RTO table from the database (stage 2.5a), same shape the csv gave: {state_code, number, state, city}.
    Letter codes (e.g. 08AA) are left out, as with the csv."""
    with require_engine().connect() as conn:
        rows = conn.execute(select(RtoCode.state_code, RtoCode.number, State.name, RtoCode.city)
                            .join(State, State.code == RtoCode.state_code).order_by(RtoCode.id)).all()
    return [{"state_code": code, "number": int(number), "state": state, "city": city}
            for code, number, state, city in rows if number.isdigit()]


@pinned
def start_confirm(run_id: str) -> dict | None:
    """Emit awaiting_confirm once and return the payload; None (node skipped) when verify has no answer."""
    saved = load_payload(run_id)
    if saved is not None:  # graph resume re-runs the node: no second set of events
        return saved
    verify = load_verify_answer(run_id)
    if not verify:
        append_event(run_id, "confirm", "node_skipped", {"reason": "Verify has no answer"})
        return None
    cfg = get_config()
    payload = build_payload(verify, rto_rows(),
                            cfg.confirm.expand_below_confidence, cfg.confirm.year_range,
                            datetime.now().year)
    save_result(run_id, PAYLOAD_FILE, payload)
    append_event(run_id, "confirm", "node_started", {"label": "Waiting for you to confirm the details"})
    append_event(run_id, "confirm", "awaiting_confirm", payload)
    return payload


@pinned
def finish_confirm(run_id: str, payload: dict, answer: dict) -> dict:
    record = build_record(payload, answer, list_photos(run_dir(run_id) / "05_photos"))
    record["confirmed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_result(run_id, RECORD_FILE, record)  # also fills confirmed_cars
    car = record["car"]
    label = " ".join(str(car[k]) for k in ("make", "model", "year") if car.get(k)) or "car details"
    append_event(run_id, "confirm", "packet", {"from": "confirm", "to": "photos", "label": label})
    append_event(run_id, "confirm", "node_done", {
        "summary": f"Confirmed; changed: {', '.join(record['changed']) or 'nothing'}",
        "files": [RECORD_FILE],
    })
    return record

