"""Pricing arithmetic: new price, yearly value kept from listings, fair value (median → max), repairs. Pure.
No LLM numbers: every input is a figure Python already checked against its source snippet."""
from __future__ import annotations

from statistics import median

NEW_PRICE_TYPES = ("on_road", "ex_showroom")
LISTING_TYPES = ("single_listing", "range")


def mid(f: dict) -> float:
    return sum(f["inr"]) / len(f["inr"])


def new_price(figures: list[dict], variant: str | None) -> dict | None:
    """Median of new-price figures: on-road preferred over ex-showroom. When a variant is given: exact name match first
    ("VXi" == "VXI"), else any variant containing it (so "VXi CNG", "VXi AMT" only count when no plain "VXi" exists)."""
    figs = [f for f in figures if f["group"] == "new_price" and f.get("type") in NEW_PRICE_TYPES]
    if not figs:
        return None
    kind = "on_road" if any(f["type"] == "on_road" for f in figs) else "ex_showroom"
    figs = [f for f in figs if f["type"] == kind]
    v = (variant or "").strip().lower()
    names = [str(f.get("variant") or "").strip().lower() for f in figs]
    exact = [f for f, n in zip(figs, names) if v and n == v]
    matched = exact or [f for f, n in zip(figs, names) if v and v in n]
    use = matched or figs
    return {"value": median(mid(f) for f in use), "type": kind, "variant_matched": bool(matched),
            "variant_match": "exact" if exact else "contains" if matched else "none",
            "sources": [f["source"] for f in use]}


def yearly_rates(figures: list[dict], new_value: float, current_year: int,
                 min_age: int = 1) -> tuple[list[dict], list[dict]]:
    """Per listing with a stated year: value kept per year = (price / new price) ^ (1 / age).
    A listing at or above today's new price is dropped (cap: nobody pays more than new). The same car on two pages
    (same year and price, and same km when stated) counts once. Listings younger than `min_age` years are dropped:
    year-1 prices swing widely, so their rate is unreliable. Returns (used, dropped)."""
    out, dropped = [], []
    seen: dict[tuple, str] = {}
    for f in figures:
        if f["group"] != "listing" or f.get("type") not in LISTING_TYPES or not isinstance(f.get("year"), int):
            continue
        age = current_year - f["year"]
        ratio = mid(f) / new_value
        if age < max(1, min_age):
            dropped.append({"source": f["source"], "year": f["year"], "price": mid(f),
                            "reason": f"under {max(1, min_age)} years old"})
            continue
        if ratio >= 1:
            dropped.append({"source": f["source"], "year": f["year"], "price": mid(f), "reason": "at or above new price"})
            continue
        key = (f["year"], round(mid(f)), f.get("km"))
        if key in seen:
            dropped.append({"source": f["source"], "year": f["year"], "price": mid(f), "reason": f"duplicate of {seen[key]}"})
            continue
        seen[key] = f["source"]
        out.append({"source": f["source"], "year": f["year"], "price": mid(f), "age": age, "rate": ratio ** (1 / age)})
    return out, dropped


def repairs(figures: list[dict], tyres: list[dict], minor_wear_inr: int) -> dict:
    """Median cost per part / tyre group, plus the fixed deduction per tyre the plan marked minor_wear."""
    groups: dict[str, list[float]] = {}
    sources: dict[str, list[str]] = {}
    for f in figures:
        if f["group"] not in ("listing", "new_price"):
            groups.setdefault(f["group"], []).append(mid(f))
            sources.setdefault(f["group"], []).append(f["url"])
    items = [{"for": g, "cost": median(v), "min": min(v), "max": max(v), "figures": len(v),
              "note": f"median of {len(v)} prices; could be up to ₹{max(v):,.0f}",
              "sources": sorted(set(sources[g]))} for g, v in groups.items()]
    items += [{"for": t.get("item_id"), "cost": minor_wear_inr, "fixed": "minor_wear (config)"}
              for t in tyres if t.get("tier") == "minor_wear"]
    return {"items": items, "total": sum(i["cost"] for i in items)}


def _round(x: float) -> int:
    return int(round(x / 1000) * 1000)


def price_report(figures: list[dict], tyres: list[dict], car: dict, current_year: int, settings: dict) -> dict:
    """settings: min_listings_with_year, tyre_minor_wear_deduction_inr, max_from_top, min_listing_age (optional, default 1).
    Range = median → max (owner: lean to max); max = average of the top `max_from_top` rates so one listing can't set it."""
    np = new_price(figures, car.get("variant"))
    rep = repairs(figures, tyres, settings["tyre_minor_wear_deduction_inr"])
    base = {"new_price": np, "repairs": rep}
    if np is None:
        return {**base, "status": "unavailable", "reason": "no new-car price found"}
    rates, over_new = yearly_rates(figures, np["value"], current_year, settings.get("min_listing_age", 1))
    base["listings_used"], base["listings_dropped"] = rates, over_new
    if len(rates) < settings["min_listings_with_year"]:
        return {**base, "status": "unavailable",
                "reason": f"{len(rates)} listings with a year, need {settings['min_listings_with_year']}"}
    r = [x["rate"] for x in rates]
    age = max(0, current_year - int(car["year"]))
    top = sorted(r)[-max(1, settings["max_from_top"]):]
    kept = {"median": median(r), "max": sum(top) / len(top)}
    fair = {k: np["value"] * v ** age for k, v in kept.items()}
    return {**base, "status": "ok", "car_age_years": age, "yearly_value_kept": kept,
            "fair_value": {k: _round(v) for k, v in fair.items()},
            "after_repairs": {k: _round(v - rep["total"]) for k, v in fair.items()}}
