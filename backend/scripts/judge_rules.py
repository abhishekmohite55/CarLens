"""
Program checks on LLM labels (owner 28 Nov 2026), used by check_judge.py --offline. Pure: no LLM, no database.
Rules were set from the owner's marks on run r_hdh1u76sly7t (judge_134037). No outlier rule.
"""
from __future__ import annotations

from app.extract import parse_usd

CAR_LIMITS = (1_000, 300_000)  # markets.us.extract_limits
LIGHT_REPAIR_BAND = (50, 400)  # midpoint of a cosmetic / minor repair price
CAR_REJECT_MATCH = {"other_model", "wrong_kind", "same_model_unknown"}
CAR_REJECT_TYPE = {"range", "starting_from"}
WORK_FOR_SEVERITY = {
    "cosmetic": {"buffing", "touch_up", "scratch_repair"},
    "minor": {"buffing", "touch_up", "scratch_repair", "repaint", "dent_repair", "chip_repair"},
}


def plan_job(group_label: str | None) -> dict:
    """'part front_bumper — scratch, cosmetic, repair' → {part, issue, severity, action}."""
    text = str(group_label or "").removeprefix("part ").strip()
    part, _, rest = text.partition(" — ")
    bits = [b.strip() for b in rest.split(",")] if rest else []
    bits += [None] * (3 - len(bits))
    return {"part": part, "issue": bits[0], "severity": bits[1], "action": bits[2]}


def program_check(row: dict, group: str) -> str:
    """'pass' or the first reject reason. row = one row of <group>_labels.json."""
    texts = row.get("price_text") or []
    texts = [texts] if isinstance(texts, str) else texts
    if not row.get("in_snippet"):
        return "price text not in snippet"
    amounts = [parse_usd(t) for t in texts]
    if not amounts or None in amounts:
        return "no number in price text"

    if group in ("new_price", "listing"):
        if row.get("match") in CAR_REJECT_MATCH:
            return f"match: {row.get('match')}"
        if row.get("type") in CAR_REJECT_TYPE:
            return f"type: {row.get('type')}"
        lo, hi = CAR_LIMITS
        if any(a < lo or a > hi for a in amounts):
            return f"amount outside ${lo:,}–${hi:,}"
        return "pass"

    # parts
    if row.get("match") != "exact":
        return f"match: {row.get('match')}"
    if row.get("car_specific") == "other_car":
        return "other car"
    job = plan_job(row.get("group_label"))
    severity = (job["severity"] or "").lower()
    if job["action"] == "repair" and severity in WORK_FOR_SEVERITY:
        if row.get("work") not in WORK_FOR_SEVERITY[severity]:
            return f"work {row.get('work')} too much for {severity} damage"
        mid = sum(amounts) / len(amounts)
        lo, hi = LIGHT_REPAIR_BAND
        if not lo <= mid <= hi:
            return f"midpoint ${mid:,.0f} outside ${lo}–${hi}"
    return "pass"
