"""Search planning helpers: which findings need the plan LLM, listing queries from templates, plan answer checks. Pure."""
from __future__ import annotations

import json
import random
import string

TYRE_TIERS = ("ok", "minor_wear", "replace")
TYRE_POSITIONS = ("front_left", "front_right", "rear_left", "rear_right")
NOT_DAMAGE_CATEGORIES = ("plate", "model_badge", "odometer", "tyre")
NO_DAMAGE_ISSUES = ("", "none", "no damage", "no visible damage")


def damage_findings(findings: list[dict]) -> list[dict]:
    """Confirmed non-tyre findings with damage: action repair/replace, a severity, or (when the locate category
    is a damage-type one) any issue other than "no visible damage"."""
    out = []
    for f in findings or []:
        if not f.get("confirmed") or f.get("tyre") or f.get("category") in NOT_DAMAGE_CATEGORIES:
            continue
        issue_says_damage = f.get("category") and str(f.get("issue") or "").strip().lower() not in NO_DAMAGE_ISSUES
        if f.get("action") in ("repair", "replace") or f.get("severity") or issue_says_damage:
            out.append(f)
    return out


def tyres_to_judge(findings: list[dict], ok_score: int) -> list[dict]:
    """Confirmed tyres scored below ok_score, or with tread worn/bald even when unscored."""
    out = []
    for f in findings or []:
        tyre = f.get("tyre") if f.get("confirmed") else None
        if not tyre:
            continue
        score = tyre.get("tyre_score")
        if (score is not None and score < ok_score) or tyre.get("tread") in ("worn", "bald"):
            out.append(f)
    return out


def tyres_not_seen(findings: list[dict]) -> list[str]:
    """Tyre positions no confirmed tyre finding covers (shown as "not assessed" in the report)."""
    seen = {(f.get("tyre") or {}).get("position") for f in findings or [] if f.get("confirmed")}
    return [p for p in TYRE_POSITIONS if p not in seen]


def car_problem(car: dict) -> str | None:
    missing = [k for k in ("make", "model") if not str((car or {}).get(k) or "").strip()]
    return f"{' and '.join(missing)} needed to plan searches" if missing else None


def listing_queries(car: dict, place: dict, templates: list[str], count: int,
                    rng: random.Random) -> tuple[list[str], list[str]]:
    """Fill templates from the confirmed car and place; skip templates with an empty field; pick `count` at random.
    Returns (queries, empty fields that made templates skip)."""
    values = {k: v for k, v in {**car, **place}.items() if v not in (None, "")}
    filled, empty = [], set()
    for t in templates:
        fields = [name for _, name, _, _ in string.Formatter().parse(t) if name]
        missing = [name for name in fields if name not in values]
        if missing:
            empty.update(missing)
            continue
        q = " ".join(t.format(**values).split())
        if q not in filled:
            filled.append(q)
    return rng.sample(filled, min(count, len(filled))), sorted(empty)


def build_user_prompt(template: str, confirm: dict, damage: list[dict], tyres: list[dict], queries_per_part: int) -> str:
    car = {**(confirm.get("car") or {}), "city": confirm.get("city"), "state": confirm.get("state"),
           "odometer_km": confirm.get("odometer_km")}
    dump = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
    return template.format(car_json=dump(car), damage_count=len(damage), damage_json=dump(damage),
                           tyre_count=len(tyres), tyres_json=dump(tyres), queries_per_part=queries_per_part)


def check_plan(parsed: dict, damage: list[dict], tyres: list[dict], queries_per_part: int) -> tuple[dict, list[str]]:
    """Drop duplicate queries; list problems (missing parts/tyres, too few queries, bad tier). Never rejects."""
    problems: list[str] = []
    seen: set[str] = set()
    parts = []
    for part in parsed.get("parts") or []:
        queries = []
        for q in part.get("queries") or []:
            key = " ".join(str(q).lower().split())
            if key and key not in seen:
                seen.add(key)
                queries.append(str(q).strip())
        if len(queries) < queries_per_part:
            problems.append(f"{part.get('part')}: {len(queries)} unique queries, want {queries_per_part}")
        parts.append({**part, "queries": queries})
    covered = {i for p in parts for i in p.get("finding_ids") or []}
    problems += [f"{f['item_id']} not covered by any part" for f in damage if f["item_id"] not in covered]

    tyre_out = []
    judged = {t.get("item_id"): t for t in parsed.get("tyres") or []}
    for f in tyres:
        t = judged.get(f["item_id"])
        if t is None:
            problems.append(f"tyre {f['item_id']} not judged")
            continue
        if t.get("tier") not in TYRE_TIERS:
            problems.append(f"tyre {f['item_id']}: tier {t.get('tier')!r} not one of {TYRE_TIERS}")
        queries = [q for q in t.get("queries") or [] if " ".join(q.lower().split()) not in seen]
        seen.update(" ".join(q.lower().split()) for q in queries)
        if t.get("tier") == "replace" and len(queries) < queries_per_part:
            problems.append(f"tyre {f['item_id']}: {len(queries)} queries, want {queries_per_part}")
        tyre_out.append({**t, "queries": queries if t.get("tier") == "replace" else []})
    return {"parts": parts, "tyres": tyre_out}, problems
