"""US plan / search / extract / pricing / report (stages U4 + U5): pure rules, no network, no database."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import MCPVIN_FIELDS
from app.extract import USD_PRICE_RE, check_figures, parse_usd, trim_results
from app.plan import market_listing_queries
from app.pricing import new_price
from app.pricing_us import original_msrp, repair_cost, state_figures, two_prices
from app.report import build_report, money
from app.search import flatten_queries
from app.vin.details import details_from, details_lines

FIXTURES = Path(__file__).parent / "fixtures" / "vin"
CAR = {"make": "MAZDA", "model": "CX-5", "variant": "Touring", "year": 2020}
TEMPLATES = ["used {year} {make} {model} for sale {state}", "{year} {make} {model} {variant} price {state}",
             "{year} {make} {model} {variant} price {state} dealer", "used {year} {make} {model} {variant} price",
             "{year} {make} {model} private party value kbb edmunds", "used {year} {make} {model} for sale carfax cargurus"]


def test_vehicle_details_from_mcpvin():
    raw = json.loads((FIXTURES / "1HGCM82643A104332.mcpvin.json").read_text(encoding="utf-8"))
    d = details_from(raw, MCPVIN_FIELDS, "recalls.recalls", 2)
    assert d["ok"] and d["recalls"] == 24 and d["complaints"] == 2013 and d["mpg_combined"] == 22
    assert d["safety_frontal_driver"] == 5 and d["open_recalls"] is None and len(d["recall_list"]) == 2
    lines = details_lines(d)
    assert lines[0] == "Recalls (model and year): 24" and "22 mpg combined" in lines[-1]
    assert details_lines({"ok": False}) == [] and details_from({}, MCPVIN_FIELDS, "recalls.recalls", 5)["ok"] is False


def test_state_queries_capped_and_tagged():
    q, groups, empty = market_listing_queries(CAR, {"state": "California", "city": None}, TEMPLATES, 4, 2,
                                              random.Random(1))
    assert len(q) == 4 and sum(1 for x in q if groups[x] == "state") == 2 and set(groups) == set(q)
    assert all("California" in x for x in q if groups[x] == "state")
    q, groups, empty = market_listing_queries(CAR, {"state": None, "city": None}, TEMPLATES, 4, 2, random.Random(1))
    assert len(q) == 3 and set(groups.values()) == {"us"} and "state" in empty  # only 3 US-wide templates exist


def test_flatten_keeps_the_group():
    out = flatten_queries({"listing": ["a", "b"], "query_groups": {"a": "state", "b": "us"}})
    assert out == [{"kind": "listing", "for": None, "query": "a", "group": "state"},
                   {"kind": "listing", "for": None, "query": "b", "group": "us"}]
    assert flatten_queries({"listing": ["a"]}) == [{"kind": "listing", "for": None, "query": "a"}]  # India unchanged


def test_parse_usd():
    assert parse_usd("$24,995") == 24995 and parse_usd("$25k") == 25000 and parse_usd("$1.2k") == 1200
    assert parse_usd("2019 CX-5 $18,995") == 18995 and parse_usd("USD 18,500") == 18500 and parse_usd("no") is None


def _search():
    return {"queries": [
        {"kind": "listing", "query": "q state", "group": "state", "results": [
            {"url": "https://a.com/1", "title": "2020 Mazda CX-5 Touring", "content": "2020 CX-5 Touring $21,500 · 41,000 mi", "score": 0.9}]},
        {"kind": "listing", "query": "q us", "group": "us", "results": [
            {"url": "https://b.com/1", "title": "Used Mazda CX-5", "content": "2019 CX-5 $19,995", "score": 0.8},
            {"url": "https://b.com/2", "title": "no price", "content": "nice car", "score": 0.7}]}]}


def test_trim_and_check_keep_the_query_group():
    t = trim_results(_search(), {}, 15, 800, USD_PRICE_RE)
    assert t["stats"]["dropped_no_price"] == 1
    assert {s["query_group"] for s in t["sources"].values()} == {"state", "us"}
    figs = [{"source": "S1", "type": "single_listing", "price_text": ["$21,500"], "about": "this_car", "year": 2020,
             "model_as_written": "CX-5"},
            {"source": "S2", "type": "single_listing", "price_text": ["$19,995"], "about": "this_car", "year": 2019}]
    limits = {"listing_min_inr": 1000, "listing_max_inr": 300000, "year_tolerance": 3, "outlier_factor": 3}
    kept, rejected = check_figures(figs, t, CAR, limits, parse_usd)
    assert rejected == [] and [(f["inr"], f["query_group"]) for f in kept] == [([21500], "state"), ([19995], "us")]


def _fig(group, price, year=None, qg=None, ftype="single_listing", source="S1", **kw):
    f = {"group": group, "type": ftype, "inr": price if isinstance(price, list) else [price], "source": source,
         "url": f"u{source}", **kw}
    if year:
        f["year"] = year
    if qg:
        f["query_group"] = qg
    return f


SETTINGS = {"min_listings_with_year": 3, "tyre_minor_wear_deduction": 50, "max_from_top": 3, "min_listing_age": 2}


def _figures(state_listings, msrp=True):
    figs = [_fig("new_price", 30000, 2020, ftype="msrp", source="N1", variant="Touring")] if msrp else []
    figs += [_fig("new_price", 36000, 2026, ftype="msrp", source="N2", variant="2.5 S Premium")]  # today's, other year
    figs += [_fig("listing", 20000 - i * 500, 2019 - i, "us", source=f"U{i}") for i in range(4)]
    figs += [_fig("listing", 21000 - i * 500, 2020 - i, "state", source=f"C{i}") for i in range(state_listings)]
    return figs


def test_india_calculator_untouched():  # owner 28 Nov: separate calculators
    assert new_price([_fig("new_price", 30000, ftype="on_road"), _fig("new_price", 25000, ftype="ex_showroom")],
                     None)["type"] == "on_road"
    assert new_price([_fig("new_price", 30000, ftype="msrp")], None) is None  # India never reads US price types


def test_original_msrp_of_the_cars_year_and_trim():
    m = original_msrp(_figures(0), CAR)
    assert m["value"] == 30000 and m["year"] == 2020 and m["variant_match"] == "exact" and m["sources"] == ["N1"]
    only_today = original_msrp(_figures(0, msrp=False), CAR)
    assert only_today is None  # today's MSRP of another year is never used as the original price
    no_year = original_msrp([_fig("new_price", 29000, ftype="msrp", source="N3")], CAR)
    assert no_year["value"] == 29000 and no_year["year"] is None


def test_repair_cost_by_action():
    scratch = [_fig("rear_bumper", [150, 500], ftype="repair_total", source="A"),
               _fig("rear_bumper", [300, 800], ftype="repair_total", source="B"),
               _fig("rear_bumper", 941, ftype="part_price", source="C")]
    minor = repair_cost(scratch, "repair", "minor")
    assert minor["cost"] == 225 and "low end" in minor["basis"] and len(minor["used"]) == 2  # no part price
    moderate = repair_cost(scratch, "repair", "moderate")
    assert moderate["cost"] == (325 + 550) / 2
    replace = repair_cost(scratch + [_fig("rear_bumper", 200, ftype="labour", source="D")], "replace", "severe")
    assert replace["cost"] == 941 + 200 and replace["basis"].startswith("part + labour")
    minor_replace = repair_cost(scratch + [_fig("rear_bumper", 200, ftype="labour", source="D")], "replace", "minor")
    assert minor_replace["cost"] == 225  # minor damage is repaired, never replaced (owner 28 Nov)
    only_parts = repair_cost([_fig("x", 400, ftype="part_price")], "repair", "minor")
    assert only_parts["basis"] == "estimate: mixed prices"
    assert repair_cost([], "repair", "minor") is None


def test_two_prices_state_shown_only_with_enough_listings():
    q = {"parts": [], "tyres": []}
    out = two_prices(_figures(3), q, CAR, 2026, SETTINGS, "California")
    assert out["status"] == "ok" and out["state"]["status"] == "ok" and out["state"]["name"] == "California"
    assert len(out["listings_used"]) == 7 and len(out["state"]["listings_used"]) == 3
    assert out["new_price"]["value"] == 30000  # the 2020 MSRP, not today's 36,000
    few = two_prices(_figures(1), q, CAR, 2026, SETTINGS, "California")
    assert few["status"] == "ok" and few["state"]["reason"] == "Not enough listings in California"
    none = two_prices(_figures(3, msrp=False), q, CAR, 2026, SETTINGS, "Texas")
    assert none["status"] == "unavailable" and none["reason"] == "no original MSRP found for this model year"
    assert none["state"]["reason"] == "Texas price unavailable: no original MSRP found for this model year"
    assert two_prices(_figures(3), q, CAR, 2026, SETTINGS, None)["state"] is None
    assert all(f["group"] != "listing" or f.get("query_group") == "state" for f in state_figures(_figures(2)))


def test_us_report():
    price = {**two_prices(_figures(3), {"parts": [], "tyres": []}, CAR, 2026, SETTINGS, "California"),
             "currency": "USD"}
    confirm = {"car": CAR, "plate": None, "city": None, "state": "California", "odometer_km": None, "changed": [],
               "skipped": [], "vin": "JM3KFBCM2L0123456", "miles_user": 48200}
    us = {"miles": {"miles_user": 48200, "miles_used": 52310, "source": "odometer", "reading_miles": 52310,
                    "unit": "mi", "accepted": True, "why": "reading accepted"},
          "vin_match": {"result": "match", "confidence": 0.9, "reason": "Mazda logo", "action": "none"},
          "details": {"ok": True, "recalls": 2, "open_recalls": 0, "complaints": 40, "mpg_combined": 28,
                      "recall_list": [{"component": "FUEL", "summary": "x"}]}}
    r = build_report({"confirm": confirm, "verify": {}, "price": price, "us": us})
    assert r["price"]["currency"] == "USD" and r["price"]["low"] > 0 and r["price"]["state"]["status"] == "ok"
    assert all("₹" not in line for line in r["price"]["how"]) and any("$" in line for line in r["price"]["how"])
    assert r["vehicle"]["vin"] == "JM3KFBCM2L0123456" and r["vehicle"]["miles_used"] == 52310
    assert r["us"]["miles"]["text"] == "52,310 mi (odometer; you typed 48,200)"
    assert r["us"]["vehicle_details"]["available"] and "Recalls (model and year): 2, 0 open for this VIN" in \
        r["us"]["vehicle_details"]["lines"]
    assert any(s.startswith("Miles: 52,310") for s in r["condition_summary"])
    assert money(24995, "USD") == "$24,995" and money(450000, "INR") == "₹4,50,000"
    no_details = build_report({"confirm": confirm, "verify": {}, "price": None, "us": {**us, "details": None}})
    assert "Recall and safety data not available." in no_details["condition_summary"]


# --- stage E2 (owner 28 Nov, run r_rbuwdpwkd6sw: "$17,600 to $17,600") ---

CAMRY = {"year": 2017, "make": "TOYOTA", "model": "Camry", "variant": "LE/SE/XLE/XSE"}


def test_msrp_exact_only_every_listed_trim_and_never_below_used():
    figs = [_fig("new_price", 24314, 2017, ftype="msrp", source="K1", variant="LE", match="exact"),
            _fig("new_price", 25084, 2017, ftype="msrp", source="K2", variant="SE", match="exact"),
            _fig("new_price", 31370, 2017, ftype="msrp", source="T1", variant="XSE", match="same_model_other_trim"),
            _fig("new_price", 14250, 2017, ftype="msrp", source="A1", variant="LE", match="exact"),  # TSRP read as MSRP
            _fig("listing", 17998, 2017, source="L1")]
    m = original_msrp(figs, CAMRY)
    assert m["sources"] == ["K1", "K2"] and m["value"] == (24314 + 25084) / 2 and m["variant_match"] == "exact"


def test_valuations_join_the_pool_trade_in_stays_out():
    figs = [_fig("new_price", 25000, 2017, ftype="msrp", source="N", variant="LE", match="exact"),
            _fig("listing", 17000, 2017, source="L1"),
            _fig("listing", 12400, 2017, ftype="private_party", source="K1"),
            _fig("listing", 13600, 2017, ftype="dealer_retail", source="K2"),
            _fig("listing", 8900, 2017, ftype="trade_in", source="K3")]
    out = two_prices(figs, {"parts": [], "tyres": []}, CAMRY, 2026, {**SETTINGS, "min_listings_with_year": 3}, None)
    assert out["status"] == "ok" and sorted(x["source"] for x in out["listings_used"]) == ["K1", "K2", "L1"]


def test_range_is_never_one_number_and_miles_move_listings():
    figs = [_fig("new_price", 25000, 2017, ftype="msrp", source="N", variant="LE", match="exact")]
    figs += [_fig("listing", 17990, 2017, source=f"L{i}", miles=80000 + i) for i in range(5)]  # 5 cars, not one twice
    q = {"parts": [], "tyres": []}
    flat = two_prices(figs, q, CAMRY, 2026, {**SETTINGS, "min_range_pct": 0.06}, None)
    lo, hi = flat["fair_value"]["median"], flat["fair_value"]["max"]
    assert hi > lo and abs((hi - lo) / ((hi + lo) / 2) - 0.06) < 0.01  # identical listings: still a 6% range
    miles = two_prices(figs, q, CAMRY, 2026, {**SETTINGS, "car_miles": 127089, "miles_per_mile": 0.05}, None)
    assert miles["listings_used"][0]["miles_adjust"] == round((80000 - 127089) * 0.05)  # -2,354: more miles, lower
    assert miles["fair_value"]["max"] < flat["fair_value"]["max"]


def test_moderate_repair_band():
    from app.extract_rules import reject_reason
    job = {"part": "front_bumper", "severity": "moderate", "action": "repair"}
    f = {"match": "exact", "work": "repaint", "car_specific": "generic"}
    assert reject_reason(f, "front_bumper", [300, 600], job, False, (1000, 300000), (50, 400), (150, 1000)) is None
    assert reject_reason(f, "front_bumper", [1500], job, False, (1000, 300000), (50, 400), (150, 1000)) == \
        "midpoint 1,500 outside 150–1,000"
    assert reject_reason(f, "front_bumper", [1500], job, False, (1000, 300000), (50, 400), None) is None
