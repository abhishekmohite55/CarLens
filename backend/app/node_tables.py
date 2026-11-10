"""A table per node (option C, owner 10 Nov 2026): the key values of a node's saved JSON as plain rows.

results.save_result() calls the writer for a path in the same transaction as the node_results row,
so the clean table and the exact JSON never disagree. One writer more per stage 2.x.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Connection

from .models import ConfirmedCar, Frame, LocateItem, VerifyFinding, VerifyVehicle


def locate_rows(response: dict) -> list[dict]:
    items = ((response or {}).get("parsed") or {}).get("items") or []
    return [{"item_id": i.get("id"), "category": i.get("category"), "label": i.get("label"),
             "side": i.get("side"), "t": i.get("t"), "t_text": i.get("t_text")} for i in items]


def frame_rows(manifest: dict) -> list[dict]:
    rows = []
    for i in (manifest or {}).get("items") or []:
        best = i.get("sharpest") or {}
        rows.append({"item_id": i.get("item_id"), "file": best.get("file"), "t": best.get("t"),
                     "sharpness": best.get("sharpness"), "frames_scored": i.get("frames_extracted"),
                     "skipped": i.get("skipped")})
    return rows


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _value(field: Any) -> Any:
    """Verify fields come as {"value": ...} (vehicle, odometer) or {"text": ...} (plate, badge)."""
    if isinstance(field, dict):
        return field.get("value", field.get("text"))
    return field


def finding_rows(parsed: dict) -> list[dict]:
    rows = []
    for f in (parsed or {}).get("findings") or []:
        tyre = f.get("tyre") or {}
        rows.append({"item_id": f.get("item_id"), "confirmed": f.get("confirmed"), "part": f.get("part"),
                     "issue": f.get("issue"), "severity": f.get("severity"), "action": f.get("action"),
                     "description": f.get("description"), "reason": f.get("reason"),
                     "tyre_position": tyre.get("position"), "tyre_score": _int(tyre.get("tyre_score")),
                     "tread": tyre.get("tread"), "best_frame": f.get("best_frame")})
    return rows


def vehicle_row(response: dict) -> dict | None:
    parsed = (response or {}).get("parsed")
    if not parsed:
        return None
    v = parsed.get("vehicle") or {}
    plate = parsed.get("plate") or {}
    answered = (response or {}).get("answered_by") or {}
    return {"make": _value(v.get("make")), "model": _value(v.get("model")), "variant": _value(v.get("variant")),
            "year": _int(_value(v.get("year"))), "fuel": _value(v.get("fuel")),
            "plate": plate.get("text"), "plate_source": plate.get("source"), "plate_confidence": plate.get("confidence"),
            "badge": _value(parsed.get("badge")), "odometer_km": _int(_value(parsed.get("odometer_km"))),
            "answered_by": answered.get("model")}


def confirmed_row(record: dict) -> dict:
    car = (record or {}).get("car") or {}
    at = (record or {}).get("confirmed_at")
    return {"make": car.get("make"), "model": car.get("model"), "variant": car.get("variant"),
            "year": _int(car.get("year")), "fuel": car.get("fuel"), "plate": record.get("plate"),
            "city": record.get("city"), "state": record.get("state"), "odometer_km": _int(record.get("odometer_km")),
            "changed": record.get("changed") or [], "skipped": record.get("skipped") or [],
            "confirmed_at": datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None}


def _write_verify(conn: Connection, run_id: str, response: Any) -> None:
    conn.execute(delete(VerifyFinding).where(VerifyFinding.run_id == run_id))
    conn.execute(delete(VerifyVehicle).where(VerifyVehicle.run_id == run_id))
    known = set(conn.execute(select(LocateItem.item_id).where(LocateItem.run_id == run_id)).scalars())
    seen: set[str] = set()
    rows = []
    for r in finding_rows((response or {}).get("parsed")):
        # A model can name an item locate never gave, or repeat one: kept in the JSON, left out of the table.
        if r["item_id"] in known and r["item_id"] not in seen:
            seen.add(r["item_id"])
            rows.append({"run_id": run_id, **r})
    if rows:
        conn.execute(insert(VerifyFinding), rows)
    vehicle = vehicle_row(response)
    if vehicle:
        conn.execute(insert(VerifyVehicle).values(run_id=run_id, **vehicle))


def _replace(model, rows_for: Callable[[Any], list[dict]]):
    def write(conn: Connection, run_id: str, data: Any) -> None:
        conn.execute(delete(model).where(model.run_id == run_id))
        rows = [{"run_id": run_id, **r} for r in rows_for(data)]
        if rows:
            conn.execute(insert(model), rows)
    return write


# Saved path → writer. The node's tables are emptied with its node_results rows (re-run, resume).
WRITERS: dict[str, Callable[[Connection, str, Any], None]] = {
    "01_locate/response.json": _replace(LocateItem, locate_rows),
    "02_frames/manifest.json": _replace(Frame, frame_rows),
    "03_verify/response.json": _write_verify,
    "04_confirm.json": _replace(ConfirmedCar, lambda record: [confirmed_row(record)]),
}
NODE_TABLES = {"locate": [LocateItem], "frames": [Frame], "verify": [VerifyFinding, VerifyVehicle],
               "confirm": [ConfirmedCar]}
