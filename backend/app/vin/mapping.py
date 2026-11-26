"""A provider's answer → the common shape (pure). The field map comes from config (vin.providers.<name>.fields):
common name → the provider's key, or a dotted path for nested answers (mcp.vin, stage U4)."""
from __future__ import annotations

from typing import Any, Mapping

# Common shape (07-us-market.md §4.2): {vin, provider, car{make, model, variant, year, fuel, body, engine, drive}, ok, error}
_EMPTY = {"", "none", "null", "not applicable", "n/a", "0"}
_LAYOUT = {"v-shaped": "V", "in-line": "I", "horizontally opposed (boxer)": "H", "w-shaped": "W"}


def _get(record: Any, path: str) -> Any:
    cur = record
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def clean(value: Any) -> str | None:
    """A provider value as text, or None when empty ("", "Not Applicable", "0" …)."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _EMPTY else text


def pick(record: Mapping, fields: Mapping[str, str]) -> dict[str, str | None]:
    """{common name: cleaned value} for every entry of the field map."""
    return {name: clean(_get(record, path)) for name, path in fields.items()}


def engine_text(displacement_l: str | None, cylinders: str | None, layout: str | None, fuel: str | None) -> str | None:
    """"3.0L V6", "1.8L I4", "2.0L 4 cyl", "Electric"; None when nothing is known."""
    if fuel and fuel.lower() == "electric" and not displacement_l:
        return "Electric"
    parts = []
    try:
        if displacement_l:
            parts.append(f"{float(displacement_l):.1f}L")
    except ValueError:
        pass
    if cylinders:
        letter = _LAYOUT.get((layout or "").lower())
        parts.append(f"{letter}{cylinders}" if letter else f"{cylinders} cyl")
    return " ".join(parts) or None


def _year(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def to_common(vin: str, provider: str, picked: Mapping[str, str | None]) -> dict:
    """The common shape. ok = make, model and year found; otherwise error "not_found" (the answer came, the car did
    not). variant = trim, else series."""
    car = {
        "make": picked.get("make"),
        "model": picked.get("model"),
        "variant": picked.get("trim") or picked.get("series"),
        "year": _year(picked.get("year")),
        "fuel": picked.get("fuel"),
        "body": picked.get("body"),
        "engine": engine_text(picked.get("displacement_l"), picked.get("cylinders"), picked.get("engine_layout"),
                              picked.get("fuel")),
        "drive": picked.get("drive"),
    }
    ok = bool(car["make"] and car["model"] and car["year"])
    return {"vin": vin, "provider": provider, "car": car, "ok": ok, "error": None if ok else "not_found"}


def not_found_message(car: Mapping[str, Any]) -> str:
    """What the user reads when the provider answered but did not give make, model and year."""
    if car.get("make") and car.get("year"):
        return (f"The VIN service knows this VIN as a {car['year']} {car['make']} but not its model. "
                "Check the number; if it is right, this car cannot be inspected yet.")
    return "We could not find a car for this VIN. Check the number."
