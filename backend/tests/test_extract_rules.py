"""Stage E1 (owner 28 Nov 2026): labelled extract rules (app/extract_rules.py) and their config. Pure, no database.
Cases follow the owner's marks on run r_hdh1u76sly7t (judge_134037)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from app.config import CONFIG_PATH, AppConfig
from app.extract import parse_inr, parse_usd
from app.extract_rules import car_text, check_labelled
from app.settings_store import check_config

NODES = ["locate", "frames", "verify", "confirm", "photos", "plan", "search", "extract", "pricing", "report"]
US_LIMITS, US_BAND, IN_LIMITS, IN_BAND = (1000, 300000), (50, 400), (100000, 10000000), (500, 5000)

TRIMMED = {"groups": [
    {"key": "new_price", "label": "new price", "items": [
        {"id": "S1", "title": "2020 CX-5 MSRP", "snippet": "CX-5 Touring $26,730 | $28,130 | CX-5 Grand Touring $30,210"}]},
    {"key": "listing", "label": "listing", "items": [
        {"id": "S2", "title": "Used CX-5", "snippet": "2019 CX-5 Touring $18,415 75,099 mi; starting at $15,315; "
                                                     "CX-30 $20,958; $5,694 to $27,998; private party $16,810"}]},
    {"key": "front_bumper", "label": "part front_bumper — scratch, cosmetic, repair", "items": [
        {"id": "S3", "title": "Bumper repair", "snippet": "polish $75–$150; repaint $300 – $600; new bumper $1500; "
                                                         "BMW X5 estimate $1425"}]},
    {"key": "rear_bumper", "label": "part rear_bumper — scratch, minor, repair", "items": [
        {"id": "S4", "title": "Rear bumper", "snippet": "repaint $150–$400; shops charge $1000 to $3300"}]},
    {"key": "left_mirror", "label": "part left_mirror — broken, moderate, replace", "items": [
        {"id": "S5", "title": "Mirror", "snippet": "OEM mirror $412.99; labor $120"}]},
    {"key": "T1", "label": "tyre T1 front_left — replace", "items": [
        {"id": "S6", "title": "Tires", "snippet": "225/55R19 $189.99; tire rack $40"}]}],
    "sources": {"S1": {"url": "u1", "group": "new_price"}, "S2": {"url": "u2", "group": "listing", "query_group": "state"},
                "S3": {"url": "u3", "group": "front_bumper"}, "S4": {"url": "u4", "group": "rear_bumper"},
                "S5": {"url": "u5", "group": "left_mirror"}, "S6": {"url": "u6", "group": "T1"}}}
PLAN = {"parts": [{"part": "front_bumper", "issue": "scratch", "severity": "cosmetic", "action": "repair"},
                  {"part": "rear_bumper", "issue": "scratch", "severity": "minor", "action": "repair"},
                  {"part": "left_mirror", "issue": "broken", "severity": "moderate", "action": "replace"}]}


def _car(src, price, **labels):
    return {"source": src, "price_text": price if isinstance(price, list) else [price], **labels}


FIGURES = [
    _car("S1", "$28,130", trim="Touring", drivetrain="AWD", type="msrp", match="exact", reason="same trim",
         confidence={"trim": 0.9, "match": 0.9}),
    _car("S1", "$26,730", trim="Touring", drivetrain="FWD", type="msrp", match="same_model_other_trim"),
    _car("S1", "$30,210", trim="Grand Touring", type="msrp", match="same_model_other_trim"),
    _car("S2", "$18,415", year=2019, trim="Touring", miles=75099, type="single_listing", match="same_model_other_year"),
    _car("S2", "$15,315", year=2022, type="starting_from", match="same_model_other_year"),
    _car("S2", "$20,958", model="CX-30", type="single_listing", match="other_model"),
    _car("S2", ["$5,694", "$27,998"], type="range", match="same_model_other_trim"),
    _car("S2", "$16,810", year=2020, trim="Touring", type="private_party", match="exact"),
    _car("S3", ["$75", "$150"], work="buffing", new_or_repair="repair", car_specific="generic", match="exact"),
    _car("S3", ["$300", "$600"], work="repaint", new_or_repair="repair", car_specific="generic", match="exact"),
    _car("S3", "$1500", work="new_part", new_or_repair="new_part", car_specific="this_car", match="other_work"),
    _car("S3", "$1425", work="scratch_repair", new_or_repair="repair", car_specific="other_car", match="exact"),
    _car("S4", ["$150", "$400"], work="repaint", new_or_repair="repair", car_specific="generic", match="exact"),
    _car("S4", ["$1000", "$3300"], work="scratch_repair", new_or_repair="repair", car_specific="this_car", match="exact"),
    _car("S5", "$412.99", work="new_part", new_or_repair="new_part", car_specific="this_car", match="exact"),
    _car("S5", "$120", work="labour", new_or_repair="labour", car_specific="generic", match="exact"),
    _car("S6", "$189.99", type="tyre_price", tyre_size="225/55R19", about="this_item"),
    _car("S6", "$40", type="other", about="not_this_item"),
    _car("S1", "$99,999", match="exact", type="msrp"),  # not in the snippet
    _car("S9", "$1", match="exact"),  # unknown source
]


def _run():
    kept, rejected = check_labelled(FIGURES, TRIMMED, PLAN, US_LIMITS, US_BAND, parse_usd, 3)
    return {(f["source"], f["price_text"][0]): f for f in kept}, {(f["source"], f["price_text"][0]): f for f in rejected}


def test_car_prices_keep_other_trims_and_years_reject_the_rest():
    kept, rejected = _run()
    assert {("S1", "$28,130"), ("S1", "$26,730"), ("S1", "$30,210"), ("S2", "$18,415"), ("S2", "$16,810")} <= set(kept)
    assert rejected[("S2", "$15,315")]["reason"] == "type: starting_from"
    assert rejected[("S2", "$20,958")]["reason"] == "match: other_model"
    assert rejected[("S2", "$5,694")]["reason"] == "type: range"
    assert rejected[("S1", "$99,999")]["reason"] == "price text not in snippet"
    assert rejected[("S9", "$1")]["reason"] == "unknown source id"


def test_kept_car_figure_has_the_classic_fields():
    kept, _ = _run()
    f = kept[("S1", "$28,130")]
    assert (f["group"], f["url"], f["inr"], f["variant"], f["about"]) == ("new_price", "u1", [28130], "Touring", "this_car")
    assert f["llm_reason"] == "same trim" and "reason" not in f and f["confidence"]["match"] == 0.9
    listing = kept[("S2", "$16,810")]
    assert listing["valuation"] == "private_party" and listing["query_group"] == "state"


def test_parts_follow_the_owner_marks():
    kept, rejected = _run()
    assert kept[("S3", "$75")]["type"] == "repair_total"                       # buffing a cosmetic scratch
    assert rejected[("S3", "$300")]["reason"] == "work repaint too much for cosmetic damage"
    assert rejected[("S3", "$1500")]["reason"] == "match: other_work"          # new part for a repair job
    assert rejected[("S3", "$1425")]["reason"] == "other car"
    assert kept[("S4", "$150")]["type"] == "repair_total"                      # repaint is fine for minor damage
    assert rejected[("S4", "$1000")]["reason"] == "midpoint 2,150 outside 50–400"


def test_replace_job_has_no_band_and_maps_part_and_labour():
    kept, _ = _run()
    assert kept[("S5", "$412.99")]["type"] == "part_price" and kept[("S5", "$120")]["type"] == "labour"


def test_tyres_as_before():
    kept, rejected = _run()
    assert kept[("S6", "$189.99")]["type"] == "tyre_price" and "about" in kept[("S6", "$189.99")]
    assert rejected[("S6", "$40")]["reason"] == "LLM: not this item"


def test_india_band_and_limits_in_rupees():
    trimmed = {"groups": [
        {"key": "listing", "label": "listing", "items": [{"id": "S1", "title": "Used Swift", "snippet": "₹4.95 lakh; ₹45,000"}]},
        {"key": "door", "label": "part door — scratch, minor, repair", "items": [
            {"id": "S2", "title": "Door", "snippet": "painting ₹2,500 per panel; full repair ₹12,000"}]}],
        "sources": {"S1": {"url": "u1", "group": "listing"}, "S2": {"url": "u2", "group": "door"}}}
    plan = {"parts": [{"part": "door", "severity": "minor", "action": "repair"}]}
    figs = [_car("S1", "₹4.95 lakh", year=2019, trim="VXi", type="single_listing", match="exact"),
            _car("S1", "₹45,000", type="single_listing", match="exact"),
            _car("S2", "₹2,500", work="repaint", car_specific="generic", match="exact"),
            _car("S2", "₹12,000", work="repaint", car_specific="generic", match="exact")]
    kept, rejected = check_labelled(figs, trimmed, plan, IN_LIMITS, IN_BAND, parse_inr, 3)
    assert [(f["source"], f["inr"]) for f in kept] == [("S1", [495000]), ("S2", [2500])]
    assert [f["reason"] for f in rejected] == ["listing amount outside limits", "midpoint 12,000 outside 500–5,000"]


def test_car_text():
    car = {"year": 2020, "make": "MAZDA", "model": "CX-5", "variant": "Touring", "fuel": "Gasoline", "drive": "AWD"}
    assert car_text(car) == "2020 MAZDA CX-5 Touring · fuel: Gasoline · drive: AWD"
    assert car_text({}) == "unknown car"


def _file_data() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_config_modes_and_bands():
    cfg = AppConfig(**_file_data())
    assert cfg.markets.in_.extract_mode == "classic" and cfg.markets.us.extract_mode == "labels"
    assert (cfg.markets.in_.light_repair_band.min, cfg.markets.in_.light_repair_band.max) == IN_BAND
    assert (cfg.markets.us.light_repair_band.min, cfg.markets.us.light_repair_band.max) == US_BAND


def test_bad_mode_and_band_are_refused():
    data = _file_data()
    data["markets"]["in"]["extract_mode"] = "smart"
    data["markets"]["us"]["light_repair_band"] = {"min": 400, "max": 50}
    fields = {p["field"] for p in check_config(data, NODES)[1]}
    assert {"markets.in.extract_mode", "markets.us.light_repair_band"} <= fields
