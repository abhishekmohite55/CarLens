"""Extract helpers: trim Tavily results into a small, grouped text for the extract LLM. Pure."""
from __future__ import annotations

import re
from urllib.parse import urlparse

PRICE_RE = re.compile(r"₹|\bRs\.?\s?\d|\bINR\b|\blakhs?\b|\d\s?/-", re.I)


def has_price(text: str | None) -> bool:
    return bool(text and PRICE_RE.search(text))


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def car_line(confirm: dict) -> str:
    car = confirm.get("car") or {}
    name = " ".join(str(car[k]) for k in ("make", "model", "variant", "year", "fuel") if car.get(k))
    km = confirm.get("odometer_km")
    place = confirm.get("city") or confirm.get("state")
    return " · ".join(x for x in (name, place, f"{km:,} km" if km else None) if x)


def _group_labels(plan_queries: dict) -> dict[str, str]:
    labels = {"listing": "listing", "new_price": "new price"}
    for p in plan_queries.get("parts") or []:
        what = ", ".join(str(p[k]) for k in ("issue", "severity", "action") if p.get(k))
        labels[p.get("part")] = f"part {p.get('part')}" + (f" — {what}" if what else "")
    for t in plan_queries.get("tyres") or []:
        labels[t.get("item_id")] = f"tyre {t.get('item_id')} {t.get('position') or ''} — {t.get('tier')}".replace("  ", " ")
    return labels


def trim_results(search: dict, plan_queries: dict, max_per_group: int, max_chars: int) -> dict:
    """Group results by what they price (listing / part / tyre), keep only snippets with a price, each URL once per
    group, best Tavily score first, at most max_per_group. Ids S1.. map back to the full URL in `sources`."""
    labels = _group_labels(plan_queries)
    order: list[str] = []
    candidates: dict[str, dict[str, dict]] = {}
    stats = {"results_in": 0, "dropped_no_price": 0, "dropped_duplicate": 0, "dropped_over_cap": 0, "kept": 0,
             "chars_in": 0}
    for q in search.get("queries") or []:
        key = q.get("kind") if q.get("kind") in ("listing", "new_price") else q.get("for")
        if key not in candidates:
            order.append(key)
            candidates[key] = {}
        for r in q.get("results") or []:
            stats["results_in"] += 1
            stats["chars_in"] += len(r.get("content") or "") + len(r.get("raw_content") or "")
            if not has_price(r.get("content")):
                stats["dropped_no_price"] += 1
            elif r["url"] in candidates[key]:
                stats["dropped_duplicate"] += 1
            else:
                candidates[key][r["url"]] = r

    groups, sources, n = [], {}, 0
    for key in order:
        ranked = sorted(candidates[key].values(), key=lambda r: r.get("score") or 0, reverse=True)
        stats["dropped_over_cap"] += max(0, len(ranked) - max_per_group)
        items = []
        for r in ranked[:max_per_group]:
            n += 1
            sid = f"S{n}"
            sources[sid] = {"url": r["url"], "title": r.get("title"), "group": key}
            items.append({"id": sid, "domain": domain_of(r["url"]), "title": " ".join(str(r.get("title") or "").split()),
                          "snippet": " ".join(str(r.get("content") or "").split())[:max_chars]})
        stats["kept"] += len(items)
        groups.append({"key": key, "label": labels.get(key, str(key)), "items": items})
    return {"groups": groups, "sources": sources, "stats": stats}


def render_trimmed(car: str, trimmed: dict) -> str:
    """The exact text the extract LLM gets."""
    lines = [f"CAR: {car}", ""]
    for g in trimmed["groups"]:
        lines.append(f"[{g['label']}]")
        if not g["items"]:
            lines.append("(no results with a price)")
        for it in g["items"]:
            lines.append(f"{it['id']} {it['domain']} | {it['title']}")
            lines.append(f"   \"{it['snippet']}\"")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|lac|l\b|k\b|crores?|cr\b)?", re.I)
_UNIT = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "l": 100_000, "k": 1_000,
         "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000}


def parse_inr(text: str) -> int | None:
    """'₹4.50 lakh' → 450000, '₹ 4,95,000' → 495000, 'Rs. 1,995' → 1995, '₹28k' → 28000. None if no number."""
    matches = list(_AMOUNT_RE.finditer(text or ""))
    if not matches:
        return None
    # "₹ 6.99 - 11.16 Lakh": the first number takes the unit written later in the same text
    unit = next((m.group(2) for m in matches if m.group(2)), None)
    value = float(matches[0].group(1).replace(",", ""))
    return round(value * _UNIT.get((matches[0].group(2) or unit or "").lower(), 1))


def _squash(text: str) -> str:
    return " ".join(str(text or "").lower().split())


CAR_GROUPS = ("listing", "new_price")


def _median(values: list[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def outlier_values(values: list[float], factor: float) -> tuple[list[float], list[float]]:
    """Split into (kept, dropped): dropped = above factor × or below 1/factor × the median. Works from 2 values."""
    if len(values) < 2:
        return list(values), []
    m = _median(values)
    kept = [v for v in values if m / factor <= v <= m * factor]
    return kept, [v for v in values if v not in kept]


def median_to_max(values: list[float]) -> list[int]:
    """Several prices in one figure → [median, max] (owner rule, leaning to the higher price)."""
    return sorted({round(_median(values)), round(max(values))})


def check_figures(figures: list[dict], trimmed: dict, car: dict, limits: dict) -> tuple[list[dict], list[dict]]:
    """Keep figures whose price text is in the snippet and (car groups) is at least listing_min_inr, matches the car's
    model and year ± year_tolerance. Parts/tyres have no amount limit. A figure with more than 2 prices becomes
    median → max after outlier removal. Group comes from the source id, never from the LLM.
    limits: listing_min_inr, listing_max_inr, year_tolerance, outlier_factor. Returns (kept, rejected with reason)."""
    items = {it["id"]: it for g in trimmed["groups"] for it in g["items"]}
    model = _squash(car.get("model"))
    kept, rejected = [], []
    for f in figures or []:
        sid = f.get("source")
        texts = f.get("price_text") or []
        texts = [texts] if isinstance(texts, str) else texts

        def reject(reason: str) -> None:
            rejected.append({**f, "reason": reason})

        if sid not in items:
            reject("unknown source id"); continue
        group = trimmed["sources"][sid]["group"]
        if f.get("about") == "not_this_item":
            reject("LLM: not this car/item"); continue
        if not texts or any(_squash(t) not in _squash(items[sid]["snippet"]) for t in texts):
            reject("price text not in snippet"); continue
        amounts = [parse_inr(t) for t in texts]
        if None in amounts:
            reject("no number in price text"); continue
        if group in CAR_GROUPS:
            if any(a < limits["listing_min_inr"] or a > limits["listing_max_inr"] for a in amounts):
                reject(f"{group} amount outside limits"); continue
            year = f.get("year") if group == "listing" else None
            if isinstance(year, int) and car.get("year") and abs(year - car["year"]) > limits["year_tolerance"]:
                reject(f"year {year} too far from {car['year']}"); continue
            seen_as = _squash(f.get("model_as_written")) + " " + _squash(items[sid]["title"])
            if model and model not in seen_as:
                reject("model does not match"); continue
        extra = {}
        if len(amounts) > 2:  # several prices lumped into one figure
            used, dropped = outlier_values(amounts, limits["outlier_factor"])
            extra = {"collapsed_from": sorted(amounts), "collapsed_outliers": dropped}
            amounts = median_to_max(used)
        kept.append({**f, "group": group, "url": trimmed["sources"][sid]["url"], "inr": sorted(amounts), **extra})
    return kept, rejected


def drop_outliers(kept: list[dict], factor: float) -> tuple[list[dict], list[dict]]:
    """Parts and tyres only: per group, drop figures whose midpoint is above factor × or below 1/factor × the group
    median (2+ figures). Car prices use the ₹ floor and the new-price cap instead."""
    by_group: dict[str, list[dict]] = {}
    for f in kept:
        by_group.setdefault(f["group"], []).append(f)
    out, dropped = [], []
    for group, figs in by_group.items():
        if group in CAR_GROUPS:
            out += figs
            continue
        median = _median([sum(f["inr"]) / len(f["inr"]) for f in figs])
        for f in figs:
            mid = sum(f["inr"]) / len(f["inr"])
            if len(figs) >= 2 and (mid > median * factor or mid < median / factor):
                dropped.append({**f, "reason": f"outlier vs group median {round(median)}"})
            else:
                out.append(f)
    return out, dropped


def group_summary(kept: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for f in kept:
        g = out.setdefault(f["group"], {"figures": 0, "min_inr": None, "max_inr": None})
        g["figures"] += 1
        g["min_inr"] = min(f["inr"][0], g["min_inr"] if g["min_inr"] is not None else f["inr"][0])
        g["max_inr"] = max(f["inr"][-1], g["max_inr"] or 0)
    return out
