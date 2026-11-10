"""A table per node (option C, owner 10 Nov 2026): the key values of a node's saved JSON as plain rows.

results.save_result() calls the writer for a path in the same transaction as the node_results row,
so the clean table and the exact JSON never disagree. One writer more per stage 2.x.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from .models import (ConfirmedCar, Frame, LocateItem, NodeResult, PhotoResult, PlanQuery, SearchResult, VerifyFinding,
                     VerifyVehicle)
from .search import flatten_queries


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


def photo_rows(response: dict, applied: dict) -> list[dict]:
    """One row per photo the model answered for; used = it changed a tyre or the km (applied.json)."""
    used_tyres = {t["slot"] for t in (applied or {}).get("tyres_replaced") or []} | set((applied or {}).get("tyres_added") or [])
    km_used = bool(((applied or {}).get("km") or {}).get("used"))
    rows = []
    for p in ((response or {}).get("parsed") or {}).get("photos") or []:
        if not isinstance(p, dict) or not p.get("slot"):
            continue
        tyre = p.get("tyre") or {}
        rows.append({"slot": p["slot"], "file": f"05_photos/{p['slot']}.jpg", "tyre_score": _int(tyre.get("tyre_score")),
                     "tread": tyre.get("tread"), "odometer_km": _int(p.get("odometer_km")),
                     "confidence": p.get("confidence") if isinstance(p.get("confidence"), (int, float)) else None,
                     "used": km_used if p["slot"] == "odometer" else p["slot"] in used_tyres})
    return rows


def _write_photos(conn: Connection, run_id: str, applied: Any) -> None:
    # applied.json is saved last; the scores come from the response row saved just before it
    response = conn.execute(select(NodeResult.data).where(
        NodeResult.run_id == run_id, NodeResult.node == "photos", NodeResult.name == "response.json")).scalar()
    conn.execute(delete(PhotoResult).where(PhotoResult.run_id == run_id))
    rows = [{"run_id": run_id, **r} for r in photo_rows(response, applied)]
    if rows:
        conn.execute(insert(PhotoResult), rows)


def plan_rows(queries: dict) -> list[dict]:
    """One row per query search will run; tyre rows carry the tier the plan LLM gave."""
    tiers = {t.get("item_id"): t.get("tier") for t in (queries or {}).get("tyres") or []}
    return [{"kind": q["kind"], "for_item": q["for"], "query": q["query"],
             "tier": tiers.get(q["for"]) if q["kind"] == "tyre" else None} for q in flatten_queries(queries or {})]


def name_key(text: str | None, make: str | None = None) -> str | None:
    """Lookup form of a car name: lowercase, single spaces, the make removed from the model ("Maruti Suzuki Ertiga" → "ertiga")."""
    if not text:
        return None
    key = " ".join(str(text).lower().split())
    m = " ".join(str(make).lower().split()) if make else ""
    if m and key.startswith(m + " "):
        key = key[len(m) + 1:]
    return key or None


def search_rows(results: dict, car: dict) -> list[dict]:
    """Every Tavily result once per (url, snippet), with the query that found it first and the run's car."""
    make = car.get("make")
    base = {"make_key": name_key(make), "model_key": name_key(car.get("model"), make), "year": _int(car.get("year"))}
    seen: set[tuple[str, str]] = set()
    rows = []
    for q in (results or {}).get("queries") or []:
        for r in q.get("results") or []:
            key = (r.get("url"), r.get("content") or "")
            if not key[0] or key in seen:
                continue
            seen.add(key)
            rows.append({"url": key[0], "snippet": key[1], "title": r.get("title"), "kind": q.get("kind"),
                         "for_item": q.get("for"), "query": q.get("query"), **base})
    return rows


def _write_search(conn: Connection, run_id: str, results: Any) -> None:
    """Upsert into search_results: kept across runs; a result seen again only gets a new last_seen_at (owner, 9 Nov)."""
    record = conn.execute(select(NodeResult.data).where(
        NodeResult.run_id == run_id, NodeResult.node == "confirm", NodeResult.name == "04_confirm.json")).scalar()
    rows = [{**r, "first_run_id": run_id} for r in search_rows(results, (record or {}).get("car") or {})]
    if not rows:
        return
    stmt = pg_insert(SearchResult).values(rows)
    conn.execute(stmt.on_conflict_do_update(index_elements=[SearchResult.url, func.md5(SearchResult.snippet)],
                                            set_={"last_seen_at": func.now()}))


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
    "05_photos/applied.json": _write_photos,
    "06_plan/queries.json": _replace(PlanQuery, plan_rows),
    "07_search/results.json": _write_search,
}
NODE_TABLES = {"locate": [LocateItem], "frames": [Frame], "verify": [VerifyFinding, VerifyVehicle],
               "confirm": [ConfirmedCar], "photos": [PhotoResult],
               "plan": [PlanQuery]}
