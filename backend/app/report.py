"""Final report (PRC-5): puts confirm, verify, photos, plan and pricing together. Pure, no AI, no files:
app/nodes/report.py loads the inputs and writes 09_report/report.json."""
from __future__ import annotations

from .photos import apply_photos
from .plan import TYRE_POSITIONS, damage_findings

SIDES = ("front", "right", "rear", "left")


def inr(v) -> str:
    """Indian grouping: 1060000 -> '₹10,60,000'."""
    s = str(int(round(v)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join(([head] if head else []) + groups + [tail])


def usd(v) -> str:
    """Stage U5: 24995 -> '$24,995'."""
    return f"${int(round(v)):,}"


def money(v, currency: str = "INR") -> str:
    """The run's currency, never the visitor's (07-us-market.md §13)."""
    return usd(v) if currency == "USD" else inr(v)


def _km(v) -> str:
    return inr(v)[1:] + " km"


def _words(s) -> str:
    return str(s or "").replace("_", " ")


def build_report(inp: dict) -> dict:
    """inp: confirm, verify (parsed answer), manifest, locate_items, queries, photos_answer, price, sources
    (S-id -> {title, url}), km_min_confidence; US runs (stage U5) also `us`: {miles (03_verify/miles.json),
    vin_match (03_verify/vin_match.json), details (vehicle details or None)}. Missing parts come in as None / {}."""
    confirm = inp["confirm"]
    verify = inp.get("verify") or {}
    manifest = inp.get("manifest") or {}
    queries = inp.get("queries") or {}
    price = inp.get("price")
    sources = inp.get("sources") or {}
    items = {i["item_id"]: i for i in manifest.get("items") or []}
    findings = [{**f, "category": (items.get(f.get("item_id")) or {}).get("category")} for f in verify.get("findings") or []]
    confirm, findings, applied = apply_photos(confirm, findings, inp.get("photos_answer"), inp.get("km_min_confidence", 0.8))
    link = lambda sid: {"id": sid, **(sources.get(sid) or {})}
    currency = (price or {}).get("currency", "INR")
    fmt = lambda v: money(v, currency)  # noqa: E731
    us = inp.get("us")

    car = confirm.get("car") or {}
    changed = confirm.get("changed") or []
    if confirm.get("km_source"):
        km_from = confirm["km_source"]
    elif "odometer_km" in changed:
        km_from = "typed by the user"
    else:
        km_from = "read from the video" if confirm.get("odometer_km") is not None else "not read"
    plate_from = "changed by the user" if "plate" in changed else (
        f"read by {(verify.get('plate') or {}).get('source', 'the model')}" if confirm.get("plate") else "not read")
    vehicle = {**car, "plate": confirm.get("plate"), "city": confirm.get("city"), "state": confirm.get("state"),
               "odometer_km": confirm.get("odometer_km"), "km_from": km_from, "plate_from": plate_from, "changed": changed}

    def where(f):
        it = items.get(f.get("item_id")) or {}
        return {"time": it.get("t_text"), "side": it.get("side") if "side" in it else None,
                "frame": f"02_frames/{f['best_frame']}" if f.get("best_frame") else None}

    damage = [{"item_id": f["item_id"], "part": f.get("part"), "issue": f.get("issue"), "severity": f.get("severity"),
               "action": f.get("action"), "description": f.get("description"), **where(f)} for f in damage_findings(findings)]
    tiers = {t.get("item_id"): t.get("tier") for t in queries.get("tyres") or []}
    tyres = []
    for f in findings:
        t = f.get("tyre") if f.get("confirmed") else None
        if not t:
            continue
        photo = f.get("source") == "photo"
        tyres.append({"position": t.get("position"), "tyre_score": t.get("tyre_score"), "tread": t.get("tread"),
                      "from": "photo" if photo else "video", "tier": tiers.get(f["item_id"]) or "ok (not judged)",
                      "description": f.get("description"), "time": None if photo else where(f)["time"],
                      "frame": f"05_photos/{t.get('position')}.jpg" if photo else where(f)["frame"]})
    tyres.sort(key=lambda t: TYRE_POSITIONS.index(t["position"]) if t["position"] in TYRE_POSITIONS else 9)
    no_damage = [_words(f.get("part")) for f in findings if f.get("confirmed") and not f.get("tyre")
                 and f.get("category") in ("damage", "mirror", "windshield") and f not in damage_findings(findings)]
    rejected = [{"item_id": f.get("item_id"), "label": (items.get(f.get("item_id")) or {}).get("label"),
                 "reason": f.get("reason")} for f in findings if not f.get("confirmed")]

    seen_sides = sorted({i.get("side") for i in inp.get("locate_items") or [] if i.get("side") in SIDES}, key=SIDES.index)
    seen_tyres = {t["position"] for t in tyres}
    coverage = {"sides_seen": seen_sides, "sides_not_seen": [s for s in SIDES if s not in seen_sides],
                "tyres_not_seen": [p for p in TYRE_POSITIONS if p not in seen_tyres],
                "odometer": km_from, "plate": plate_from, "skipped": confirm.get("skipped") or [],
                "not_confirmed": rejected}

    repairs = {"items": [], "total": 0, "cost_unavailable": []}
    if price:
        for i in price["repairs"]["items"]:
            label = i["for"]
            tyre = next((t for t in findings if t.get("item_id") == label and t.get("tyre")), None)
            if tyre:
                label = f"{_words(tyre['tyre'].get('position'))} tyre"
            repairs["items"].append({"for": label, "cost": i["cost"], "up_to": i.get("max"), "note": i.get("note") or i.get("fixed"),
                                     "sources": i.get("sources") or []})
        repairs["total"] = price["repairs"]["total"]
        priced = {i["for"] for i in price["repairs"]["items"]}
        wanted = [p.get("part") for p in queries.get("parts") or []] + [t.get("item_id") for t in queries.get("tyres") or [] if t.get("tier") == "replace"]
        repairs["cost_unavailable"] = [_words(w) for w in wanted if w not in priced]

    if price and price.get("status") == "ok":
        np, k, a, fv = price["new_price"], price["yearly_value_kept"], price["after_repairs"], price["fair_value"]
        price_out = {
            "status": "ok", "low": a["median"], "high": a["max"], "fair_value": fv,
            "new_price": {**{x: np.get(x) for x in ("value", "type", "variant_match")}, "sources": [link(s) for s in np["sources"]]},
            "listings_used": [{"year": x["year"], "price": x["price"], "rate": round(x["rate"], 3), "source": link(x["source"])}
                              for x in price["listings_used"]],
            "how": [(f"Original MSRP {fmt(np['value'])} ({np.get('year') or 'year not stated'}, " if us else
                     f"New price {fmt(np['value'])} (")
                    + f"{_words(np['type'])}, variant match: {np.get('variant_match', 'n/a')}, {len(np['sources'])} source(s))",
                    f"{len(price['listings_used'])} listings 2+ years old: value kept per year median {k['median']:.3f}, "
                    f"top-3 average {k['max']:.3f}",
                    f"Car age {price['car_age_years']} years: fair value {fmt(fv['median'])} – {fmt(fv['max'])}",
                    f"Minus repairs {fmt(repairs['total'])}: {fmt(a['median'])} – {fmt(a['max'])}",
                    "Miles are not used in the price yet" if us else "Km is not used in the price"]}
    else:
        price_out = {"status": "unavailable",
                     "reason": (price or {}).get("reason") or "Pricing did not run for this run"}
    if us:
        price_out["currency"] = currency  # India's price block keeps its shape (₹ implied)
        price_out["scope"] = "US-wide"
        st = (price or {}).get("state")
        if st:  # stage U5: the state price next to the US-wide one, or why not
            price_out["state"] = ({"status": "ok", "name": st["name"], "low": st["after_repairs"]["median"],
                                   "high": st["after_repairs"]["max"], "listings": len(st.get("listings_used") or [])}
                                  if st.get("status") == "ok" else
                                  {"status": "unavailable", "name": st.get("name"), "reason": st.get("reason")})

    summary = []
    if damage:
        summary.append(f"{len(damage)} damage finding(s): " + "; ".join(
            f"{d['severity'] or ''} {_words(d['issue'])} on {_words(d['part'])}".strip() + (f" ({d['action']})" if d.get("action") not in (None, "none") else "")
            for d in damage) + ".")
    else:
        summary.append("No damage confirmed.")
    if tyres:
        summary.append("Tyres: " + "; ".join(
            f"{_words(t['position'])} {t['tyre_score'] if t['tyre_score'] is not None else '?'}/10 {t['tread'] or ''}".strip()
            + (" (photo)" if t["from"] == "photo" else "") for t in tyres)
            + (f". Not seen: {', '.join(_words(p) for p in coverage['tyres_not_seen'])}." if coverage["tyres_not_seen"] else "."))
    else:
        summary.append("Tyres not assessed.")
    if no_damage:
        summary.append("Checked, no damage: " + ", ".join(no_damage) + ".")
    if rejected:
        summary.append(f"{len(rejected)} item(s) flagged in the video were not confirmed (e.g. reflections).")
    if us:
        us_out = _us_part(us, confirm)
        summary += us_out.pop("summary")
        vehicle.update(us_out.pop("vehicle"))
        coverage["odometer"] = us_out["miles"]["text"]
        coverage["plate"] = vehicle["plate_from"] = "not used (US: car from the VIN)"
    else:
        summary.append(f"Odometer: {_km(confirm['odometer_km']) + ' (' + km_from + ')' if confirm.get('odometer_km') is not None else 'not read'}.")

    out = {"vehicle": vehicle, "price": price_out, "condition_summary": summary, "damage": damage, "tyres": tyres,
           "repairs": repairs, "coverage": coverage, "photos_applied": applied}
    if us:
        out["us"] = us_out
    return out


def _us_part(us: dict, confirm: dict) -> dict:
    """Stage U5: the US-only part of the report — VIN, miles used and why, video vs VIN, recalls / safety / mpg."""
    from .vin.details import details_lines  # imported here: report stays importable without the vin package users

    miles = us.get("miles") or {}
    used, source = miles.get("miles_used", confirm.get("miles_user")), miles.get("source", "you")
    if source == "odometer":
        text = f"{used:,} mi (odometer; you typed {miles.get('miles_user'):,})"
    elif miles.get("reading_miles") is not None:
        text = f"{used:,} mi (you typed; odometer {miles['reading_miles']:,} mi, {miles.get('why')})"
    else:
        text = f"{used:,} mi (you typed; odometer not read)" if used is not None else "not known"
    match = us.get("vin_match") or {}
    details = us.get("details")
    lines = details_lines(details)
    summary = [f"Miles: {text}."]
    if match.get("action") == "warn":
        summary.append(f"Warning: the video may not show the car of this VIN ({match.get('reason') or 'mismatch'}).")
    elif match.get("result") == "unsure":
        summary.append("The car in the video could not be matched to the VIN (not enough seen).")
    summary.append(" ".join(f"{x}." for x in lines) if lines else "Recall and safety data not available.")
    return {"vehicle": {"vin": confirm.get("vin"), "state_code": confirm.get("state_code"), "miles_used": used,
                        "miles_source": source},
            "miles": {"used": used, "source": source, "user": miles.get("miles_user", confirm.get("miles_user")),
                      "odometer": miles.get("reading_miles"), "odometer_unit": miles.get("unit"),
                      "accepted": miles.get("accepted"), "why": miles.get("why"), "text": text},
            "vin_match": {k: match.get(k) for k in ("result", "confidence", "reason", "action")} if match else None,
            "vehicle_details": {"available": bool(lines), "lines": lines,
                                "recalls": (details or {}).get("recall_list") or []},
            "summary": summary}
