import random

from app.plan import car_problem, check_plan, damage_findings, listing_queries, tyres_not_seen, tyres_to_judge

FINDINGS = [
    {"item_id": "L1", "confirmed": True, "action": "none", "severity": None, "issue": "no visible damage"},
    {"item_id": "L2", "confirmed": True, "action": "repair", "severity": "minor", "issue": "dent"},
    {"item_id": "L3", "confirmed": False, "reason": "reflection"},
    {"item_id": "L4", "confirmed": True, "action": "none", "tyre": {"tyre_score": 7}},
    {"item_id": "L5", "confirmed": True, "action": "none", "tyre": {"tyre_score": 4}},
    {"item_id": "L6", "confirmed": True, "action": "none", "tyre": {"tyre_score": None}},
]


def test_selects_damage_and_tyres():
    assert [f["item_id"] for f in damage_findings(FINDINGS)] == ["L2"]
    assert [f["item_id"] for f in tyres_to_judge(FINDINGS, 7)] == ["L5"]


def test_listing_skips_empty_fields_and_samples():
    car = {"make": "Maruti Suzuki", "model": "Swift", "variant": None, "year": 2022, "fuel": "Petrol"}
    templates = ["used {make} {model} {year} {city}", "{make} {model} {variant} {year}", "second hand {model} {state}"]
    out, empty = listing_queries(car, {"city": "Pune", "state": "Maharashtra"}, templates, 4, random.Random(1))
    assert empty == ["variant"]
    assert sorted(out) == ["second hand Swift Maharashtra", "used Maruti Suzuki Swift 2022 Pune"]


def test_check_plan_dedupes_and_reports():
    parsed = {"parts": [{"part": "door", "finding_ids": ["L2"], "queries": ["a b", "A  b", "c"]}],
              "tyres": [{"item_id": "L5", "tier": "minor_wear", "queries": ["x"]}]}
    plan, problems = check_plan(parsed, damage_findings(FINDINGS), tyres_to_judge(FINDINGS, 7), 2)
    assert plan["parts"][0]["queries"] == ["a b", "c"]
    assert plan["tyres"][0]["queries"] == []  # minor_wear: no Tavily
    assert problems == []
    _, problems = check_plan({"parts": []}, damage_findings(FINDINGS), tyres_to_judge(FINDINGS, 7), 2)
    assert problems == ["L2 not covered by any part", "tyre L5 not judged"]


def test_damage_by_issue_only_when_category_known():
    scratch = {"item_id": "L7", "confirmed": True, "action": "none", "severity": None, "issue": "scratch",
               "category": "damage"}
    badge = {"item_id": "L8", "confirmed": True, "action": "none", "severity": None, "issue": "SWIFT badge visible",
             "category": "model_badge"}
    clean = {**scratch, "item_id": "L9", "issue": "No visible damage"}
    assert [f["item_id"] for f in damage_findings([scratch, badge, clean])] == ["L7"]


def test_unscored_bald_tyre_is_judged():
    bald = {"item_id": "L10", "confirmed": True, "tyre": {"tyre_score": None, "tread": "bald"}}
    assert tyres_to_judge([bald], 7) == [bald]


def test_tyres_not_seen():
    assert tyres_not_seen(FINDINGS) == ["front_left", "front_right", "rear_left", "rear_right"]
    seen = [{"confirmed": True, "tyre": {"position": "front_left"}}, {"confirmed": False, "tyre": {"position": "rear_left"}}]
    assert tyres_not_seen(seen) == ["front_right", "rear_left", "rear_right"]


def test_listing_reports_empty_fields_and_car_problem():
    _, empty = listing_queries({"make": "Tata", "model": "Nexon", "year": 2021}, {"city": None},
                               ["used {make} {model} {city}", "{model} {year}"], 4, random.Random(1))
    assert empty == ["city"]
    assert car_problem({"make": "Tata", "model": " "}) == "model needed to plan searches"
    assert car_problem({"make": "Tata", "model": "Nexon"}) is None
