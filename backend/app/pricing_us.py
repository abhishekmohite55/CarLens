"""US price calculator (owner, 28 Nov 2026): separate from India's app/pricing.py so a change to one never touches the
other. Pure: no config reads, no database, no events. Every number is a figure Python already checked in its snippet.

Method (owner, 28 Nov):
- New price = the car's **original MSRP** (its model year and trim), not today's price of a trim that may be gone.
- Value kept per year from each listing = (listing / original MSRP) ^ (1 / listing age); fair value = original MSRP ×
  kept ^ car age (median → average of the top rates, as India). A listing at or above the MSRP is dropped.
- Repairs by what verify said to do: a minor / cosmetic repair uses repair-job prices only (low end of each range);
  a moderate repair the median repair job; a replacement part + labour. No mixing of part prices into a scratch fix.
- Two prices: US-wide (every listing) and the state's (state-query listings only), shown only with enough listings.
"""
from __future__ import annotations

from statistics import median

LISTING_TYPES = ("single_listing", "range")
MSRP_TYPES = ("msrp", "invoice")  # preferred first
LIGHT = ("cosmetic", "minor")  # severities whose repair uses the low end of repair-job prices


def mid(f: dict) -> float:
    return sum(f["inr"]) / len(f["inr"])  # "inr" = the figure's amounts in the run's currency (key shared with extract)


def _low(f: dict) -> float:
    return min(f["inr"])


def usd(v: float) -> str:
    return f"${v:,.0f}"


def original_msrp(figures: list[dict], car: dict) -> dict | None:
    """The car's original MSRP: msrp figures (invoice only when there is no msrp) of the car's model year (or with no
    year stated); trim match exact first, else a trim containing it, else the median of every trim found."""
    figs = [f for f in figures if f["group"] == "new_price" and f.get("type") in MSRP_TYPES]
    if not figs:
        return None
    kind = next(t for t in MSRP_TYPES if any(f["type"] == t for f in figs))
    figs = [f for f in figs if f["type"] == kind]
    year = car.get("year")
    same_year = [f for f in figs if f.get("year") == year]
    figs = same_year or [f for f in figs if not isinstance(f.get("year"), int)]
    if not figs:
        return None
    v = str(car.get("variant") or "").strip().lower()
    names = [str(f.get("variant") or "").strip().lower() for f in figs]
    exact = [f for f, n in zip(figs, names) if v and n == v]
    matched = exact or [f for f, n in zip(figs, names) if v and v in n]
    use = matched or figs
    return {"value": median(mid(f) for f in use), "type": kind, "year": year if same_year else None,
            "variant_matched": bool(matched), "variant_match": "exact" if exact else "contains" if matched else "none",
            "sources": [f["source"] for f in use]}


def yearly_rates(figures: list[dict], msrp: float, current_year: int, min_age: int) -> tuple[list[dict], list[dict]]:
    """Per listing with a stated year: value kept per year against the original MSRP. Dropped: younger than min_age,
    at or above the MSRP, the same car twice (same year, price and miles)."""
    out, dropped = [], []
    seen: dict[tuple, str] = {}
    for f in figures:
        if f["group"] != "listing" or f.get("type") not in LISTING_TYPES or not isinstance(f.get("year"), int):
            continue
        age, price = current_year - f["year"], mid(f)
        base = {"source": f["source"], "year": f["year"], "price": price}
        if age < max(1, min_age):
            dropped.append({**base, "reason": f"under {max(1, min_age)} years old"})
            continue
        if price >= msrp:
            dropped.append({**base, "reason": "at or above the original MSRP"})
            continue
        key = (f["year"], round(price), f.get("miles"))
        if key in seen:
            dropped.append({**base, "reason": f"duplicate of {seen[key]}"})
            continue
        seen[key] = f["source"]
        out.append({**base, "age": age, "rate": (price / msrp) ** (1 / age), "query_group": f.get("query_group")})
    return out, dropped


def repair_cost(figs: list[dict], action: str | None, severity: str | None) -> dict | None:
    """One part's cost from its figures, by what verify said to do. None when it has no figures at all.
    Owner 28 Nov: cosmetic / minor damage is always repaired (buffing, touch up, PDR, chip repair), never replaced."""
    if not figs:
        return None
    by = lambda *types: [f for f in figs if f.get("type") in types]  # noqa: E731
    jobs, parts, labour = by("repair_total"), by("part_price"), by("labour")
    if action == "replace" and severity not in LIGHT:
        if parts and labour:
            return {"cost": median(mid(f) for f in parts) + median(mid(f) for f in labour),
                    "basis": "part + labour (median of each)", "used": parts + labour}
        if jobs:
            return {"cost": median(mid(f) for f in jobs), "basis": "replacement job (median)", "used": jobs}
        if parts:
            return {"cost": median(mid(f) for f in parts), "basis": "part only (no labour price found)", "used": parts}
    else:
        light = severity in LIGHT
        for chosen, name in ((jobs, "repair job"), (labour, "labour")):
            if chosen:
                cost = median(_low(f) for f in chosen) if light else median(mid(f) for f in chosen)
                return {"cost": cost, "used": chosen,
                        "basis": f"{name}, low end of each price ({severity})" if light else f"{name} (median)"}
    return {"cost": median(mid(f) for f in figs), "basis": "estimate: mixed prices", "used": figs}


def repairs(figures: list[dict], tyres: list[dict], parts: list[dict], minor_wear: int) -> dict:
    """Cost per damaged part (repair_cost) and per tyre marked replace (median tyre price), plus the fixed deduction
    per tyre the plan marked minor_wear. parts: plan's parts [{part, action, severity}]."""
    info = {p.get("part"): p for p in parts}
    groups: dict[str, list[dict]] = {}
    for f in figures:
        if f["group"] not in ("listing", "new_price"):
            groups.setdefault(f["group"], []).append(f)
    items = []
    for group, figs in groups.items():
        p = info.get(group)
        r = (repair_cost(figs, p.get("action"), p.get("severity")) if p
             else {"cost": median(mid(f) for f in figs), "basis": "tyre price (median)", "used": figs})
        values = [mid(f) for f in r["used"]]
        items.append({"for": group, "cost": r["cost"], "min": min(values), "max": max(values), "figures": len(values),
                      "basis": r["basis"], "note": f"{r['basis']}; {len(values)} prices, up to {usd(max(values))}",
                      "sources": sorted({f["url"] for f in r["used"]})})
    items += [{"for": t.get("item_id"), "cost": minor_wear, "fixed": "minor_wear (config)"}
              for t in tyres if t.get("tier") == "minor_wear"]
    return {"items": items, "total": sum(i["cost"] for i in items)}


def _round(x: float) -> int:
    return int(round(x / 100) * 100)  # US prices to the nearest $100


def price_report(figures: list[dict], queries: dict, car: dict, current_year: int, settings: dict) -> dict:
    """settings: min_listings_with_year, max_from_top, min_listing_age, tyre_minor_wear_deduction."""
    msrp = original_msrp(figures, car)
    rep = repairs(figures, queries.get("tyres") or [], queries.get("parts") or [], settings["tyre_minor_wear_deduction"])
    base = {"new_price": msrp, "repairs": rep}
    if msrp is None:
        return {**base, "status": "unavailable", "reason": "no original MSRP found for this model year"}
    rates, dropped = yearly_rates(figures, msrp["value"], current_year, settings.get("min_listing_age", 1))
    base["listings_used"], base["listings_dropped"] = rates, dropped
    if len(rates) < settings["min_listings_with_year"]:
        return {**base, "status": "unavailable", "listings_short": True,
                "reason": f"{len(rates)} listings with a year, need {settings['min_listings_with_year']}"}
    r = [x["rate"] for x in rates]
    age = max(0, current_year - int(car["year"]))
    top = sorted(r)[-max(1, settings["max_from_top"]):]
    kept = {"median": median(r), "max": max(median(r), sum(top) / len(top))}
    fair = {k: msrp["value"] * v ** age for k, v in kept.items()}
    return {**base, "status": "ok", "car_age_years": age, "yearly_value_kept": kept,
            "fair_value": {k: _round(v) for k, v in fair.items()},
            "after_repairs": {k: _round(v - rep["total"]) for k, v in fair.items()}}


def state_figures(figures: list[dict]) -> list[dict]:
    """Figures for the state price: listings found by a {state} query, plus every new-price and repair figure."""
    return [f for f in figures if f["group"] != "listing" or f.get("query_group") == "state"]


def two_prices(figures: list[dict], queries: dict, car: dict, current_year: int, settings: dict,
               state: str | None) -> dict:
    """US-wide price + the state's (07-us-market.md §8). The state's message says the real reason: "Not enough
    listings in Texas" only when listings are short; otherwise the reason itself (e.g. no original MSRP)."""
    out = price_report(figures, queries, car, current_year, settings)
    if not state:
        return {**out, "state": None}
    st = price_report(state_figures(figures), queries, car, current_year, settings)
    if st["status"] == "ok":
        return {**out, "state": {**st, "name": state}}
    reason = f"Not enough listings in {state}" if st.get("listings_short") else f"{state} price unavailable: {st['reason']}"
    return {**out, "state": {"status": "unavailable", "name": state, "reason": reason, "detail": st.get("reason"),
                             "listings_used": st.get("listings_used") or []}}
