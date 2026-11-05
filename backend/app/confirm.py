"""Confirm step helpers: RTO city lookup, year options, expand rule, payload and record. Pure: no config, events or run folders."""
from __future__ import annotations

import csv
import re
from pathlib import Path

_RTO_PREFIX = re.compile(r"^([A-Z]{2})(\d{1,2})")
CAR_FIELDS = ("make", "model", "variant", "year", "fuel")
EXPAND_FIELDS = ("make", "model", "year")  # variant is optional (owner, 4 Nov 2026)


def load_rto(path: Path) -> list[dict]:
    """Rows of the RTO csv as {state_code, number, state, city}."""
    with open(path, encoding="utf-8", newline="") as f:
        return [
            {"state_code": r["State-code"].strip().upper(), "number": int(r["City-code"]),
             "state": r["state"].strip(), "city": r["city"].strip()}
            for r in csv.DictReader(f)
            if r.get("City-code", "").strip().isdigit()
        ]


def _is_statewide(row: dict) -> bool:
    return row["city"].lower().startswith("statewide")


def city_from_plate(plate: str | None, alternatives: list[str], rto: list[dict]) -> dict:
    """City guess from the plate's RTO code. candidates = codes read from plate + alternatives, or the state's cities."""
    hits, states = [], []
    for text in [plate or "", *alternatives]:
        m = _RTO_PREFIX.match(text)
        if not m:
            continue
        code, number = m.group(1), int(m.group(2))
        states.append(code)
        for row in rto:
            if row["state_code"] == code and row["number"] == number and not _is_statewide(row):
                cand = {"code": f"{code}{number:02d}", "city": row["city"], "state": row["state"]}
                if cand not in hits:
                    hits.append(cand)
    if hits:
        return {"value": hits[0]["city"], "state": hits[0]["state"], "candidates": hits}
    if states:  # state known, city not: offer that state's cities
        rows = [r for r in rto if r["state_code"] == states[0] and not _is_statewide(r)]
        cands = [{"code": f"{r['state_code']}{r['number']:02d}", "city": r["city"], "state": r["state"]} for r in rows]
        return {"value": None, "state": rows[0]["state"] if rows else None, "candidates": cands}
    return {"value": None, "state": None, "candidates": []}


def year_options(guess: int | None, year_range: int, current_year: int) -> list[int]:
    """Guess ± year_range, newest first, never past current_year. No guess: the last 2*year_range+1 years."""
    centre = min(guess, current_year) if guess else current_year - year_range
    return list(range(min(centre + year_range, current_year), centre - year_range - 1, -1))


def needs_expand(vehicle: dict, threshold: float) -> bool:
    """Open the form when make, model or year is missing or below threshold."""
    for name in EXPAND_FIELDS:
        field = (vehicle or {}).get(name) or {}
        if field.get("value") in (None, "") or (field.get("confidence") or 0) < threshold:
            return True
    return False


def _value(field) -> object:
    return field.get("value") if isinstance(field, dict) else None


def build_payload(verify: dict, rto: list[dict], threshold: float, year_range: int, current_year: int) -> dict:
    """awaiting_confirm payload (03-architecture.md §5.6) from verify's parsed answer."""
    vehicle = verify.get("vehicle") or {}
    plate = verify.get("plate") or {}
    year = _value(vehicle.get("year"))
    return {
        "vehicle": vehicle,
        "plate": plate,
        "odometer_km": verify.get("odometer_km"),
        "tyres_assessed": bool(verify.get("tyres_assessed")),
        "odometer_found": bool(verify.get("odometer_found")),
        "city": city_from_plate(plate.get("text"), plate.get("alternatives") or [], rto),
        "year_options": year_options(year if isinstance(year, int) else None, year_range, current_year),
        "expand": needs_expand(vehicle, threshold),
        "expand_threshold": threshold,
    }


def prefill(payload: dict) -> dict:
    """The values the form starts with, in 04_confirm.json shape."""
    vehicle = payload.get("vehicle") or {}
    city = payload.get("city") or {}
    return {
        "car": {name: _value(vehicle.get(name)) for name in CAR_FIELDS},
        "plate": (payload.get("plate") or {}).get("text"),
        "city": city.get("value"),
        "state": city.get("state"),
        "odometer_km": _value(payload.get("odometer_km")),
    }


def build_record(payload: dict, answer: dict, photos: list[dict] | None = None) -> dict:
    """04_confirm.json: final values, fields the user changed, skipped prompts, uploaded photos (05_photos/)."""
    start = prefill(payload)
    final = {
        "car": {name: (answer.get("car") or {}).get(name) for name in CAR_FIELDS},
        "plate": answer.get("plate"),
        "city": answer.get("city"),
        "state": answer.get("state"),
        "odometer_km": answer.get("odometer_km"),
    }
    changed = [n for n in CAR_FIELDS if final["car"][n] != start["car"][n]]
    changed += [n for n in ("plate", "city", "state", "odometer_km") if final[n] != start[n]]
    return {**final, "changed": changed, "skipped": list(answer.get("skipped") or []), "photos": list(photos or [])}
