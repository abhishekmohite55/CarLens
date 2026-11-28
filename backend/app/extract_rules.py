"""Stage E1 (owner 28 Nov 2026): keep or reject the labelled prices of the extract LLM. Pure.

The extract LLM copies each price and labels it (match, trim, type, work, ...; a confidence per label). These rules,
checked on run r_hdh1u76sly7t against the owner's own marks, decide what pricing may use. They replace the model-name
check and the outlier rule of the classic extract (app/extract.py check_figures / drop_outliers) for a market whose
markets.<market>.extract_mode is "labels". Kept figures keep the classic field names (group, url, inr, type, variant,
model_as_written, year, km / miles, query_group), so pricing, node tables and the inspector read them as before.
"""
from __future__ import annotations

from typing import Callable

from .extract import _squash, median_to_max, outlier_values

CAR_GROUPS = ("listing", "new_price")
CAR_REJECT_MATCH = {"other_model", "wrong_kind", "same_model_unknown"}  # other trims / years stay (depreciation)
CAR_REJECT_TYPE = {"range", "starting_from"}  # market-wide numbers, not one car
PART_REJECT_CAR = {"other_car"}
# work a cosmetic / minor damage may take (a repair job only; owner 28 Nov: light damage is repaired, never replaced)
WORK_FOR_SEVERITY = {
    "cosmetic": {"buffing", "touch_up", "scratch_repair"},
    "minor": {"buffing", "touch_up", "scratch_repair", "repaint", "dent_repair", "chip_repair"},
}
# part labels → the classic figure type the calculators read
WORK_TYPE = {"new_part": "part_price", "used_part": "part_price", "install": "labour", "labour": "labour",
             "buffing": "repair_total", "touch_up": "repair_total", "scratch_repair": "repair_total",
             "dent_repair": "repair_total", "repaint": "repair_total", "chip_repair": "repair_total",
             "full_repair_job": "repair_total"}


def car_text(car: dict) -> str:
    """'2020 MAZDA CX-5 Touring · body: SUV · engine: 2.5L I4 · fuel: Gasoline · drive: AWD' for the prompt."""
    car = car or {}
    name = " ".join(str(car[k]) for k in ("year", "make", "model", "variant") if car.get(k)) or "unknown car"
    rest = [f"{k}: {car[k]}" for k in ("body", "engine", "fuel", "transmission", "drive") if car.get(k)]
    return " · ".join([name, *rest])


def _jobs(plan_queries: dict | None) -> dict[str, dict]:
    return {p.get("part"): p for p in (plan_queries or {}).get("parts") or [] if p.get("part")}


def _is_tyre(group: str, trimmed: dict) -> bool:
    label = next((g.get("label") for g in trimmed["groups"] if g["key"] == group), "") or ""
    return str(label).startswith("tyre")


def reject_reason(f: dict, group: str, amounts: list[int], job: dict | None, tyre: bool,
                  limits: tuple[int, int], band: tuple[int, int],
                  moderate_band: tuple[int, int] | None = None) -> str | None:
    """The first rule a labelled figure breaks, or None. amounts: the parsed prices."""
    if group in CAR_GROUPS:
        if f.get("match") in CAR_REJECT_MATCH:
            return f"match: {f.get('match')}"
        if f.get("type") in CAR_REJECT_TYPE:
            return f"type: {f.get('type')}"
        if any(a < limits[0] or a > limits[1] for a in amounts):
            return f"{group} amount outside limits"
        return None
    if tyre:  # tyres: as the classic extract until the owner decides (28 Nov)
        return "LLM: not this item" if f.get("about") == "not_this_item" else None
    if f.get("match") != "exact":
        return f"match: {f.get('match')}"
    if f.get("car_specific") in PART_REJECT_CAR:
        return "other car"
    severity = str((job or {}).get("severity") or "").lower()
    if (job or {}).get("action") == "repair" and severity == "moderate" and moderate_band:  # stage E2
        mid = sum(amounts) / len(amounts)
        if not moderate_band[0] <= mid <= moderate_band[1]:
            return f"midpoint {round(mid):,} outside {moderate_band[0]:,}–{moderate_band[1]:,}"
    if (job or {}).get("action") == "repair" and severity in WORK_FOR_SEVERITY:
        if f.get("work") not in WORK_FOR_SEVERITY[severity]:
            return f"work {f.get('work')} too much for {severity} damage"
        mid = sum(amounts) / len(amounts)
        if not band[0] <= mid <= band[1]:
            return f"midpoint {round(mid):,} outside {band[0]:,}–{band[1]:,}"
    return None


def check_labelled(figures: list, trimmed: dict, plan_queries: dict | None, limits: tuple[int, int],
                   band: tuple[int, int], parse: Callable[[str], int | None],
                   outlier_factor: float, moderate_band: tuple[int, int] | None = None) -> tuple[list[dict], list[dict]]:
    """(kept, rejected with reason). Group, url and query_group come from the source id, never from the LLM."""
    items = {it["id"]: it for g in trimmed["groups"] for it in g["items"]}
    jobs = _jobs(plan_queries)
    kept, rejected = [], []
    for f in figures or []:
        if not isinstance(f, dict):
            continue
        sid = f.get("source")
        texts = f.get("price_text") or []
        texts = [texts] if isinstance(texts, str) else texts
        # the LLM's own one-line reason is kept as llm_reason; "reason" on a figure is always the program's
        own = {**{k: v for k, v in f.items() if k != "reason"}, "price_text": texts,
               **({"llm_reason": f["reason"]} if f.get("reason") else {})}

        def reject(reason: str) -> None:
            rejected.append({**own, **({"group": trimmed["sources"][sid]["group"]}
                                       if sid in trimmed["sources"] else {}), "reason": reason})

        if sid not in items:
            reject("unknown source id"); continue
        group = trimmed["sources"][sid]["group"]
        if not texts or any(_squash(t) not in _squash(items[sid]["snippet"]) for t in texts):
            reject("price text not in snippet"); continue
        amounts = [parse(t) for t in texts]
        if None in amounts:
            reject("no number in price text"); continue
        tyre = group not in CAR_GROUPS and _is_tyre(group, trimmed)
        reason = reject_reason(f, group, amounts, jobs.get(group), tyre, limits, band, moderate_band)
        if reason:
            reject(reason); continue
        extra = {}
        if len(amounts) > 2:  # several prices lumped into one figure
            used, dropped = outlier_values(amounts, outlier_factor)
            extra = {"collapsed_from": sorted(amounts), "collapsed_outliers": dropped}
            amounts = median_to_max(used)
        mapped = {}
        if group in CAR_GROUPS:
            mapped = {"about": "this_car", "variant": f.get("trim"), "model_as_written": f.get("model")}
            if f.get("type") in ("trade_in", "private_party", "dealer_retail"):
                mapped["valuation"] = f["type"]
        elif not tyre:
            mapped = {"about": "this_item", "type": WORK_TYPE.get(f.get("work"), "other")}
        qg = trimmed["sources"][sid].get("query_group")
        kept.append({**own, **mapped, "group": group, "url": trimmed["sources"][sid]["url"],
                     "inr": sorted(amounts), **extra, **({"query_group": qg} if qg else {})})
    return kept, rejected
