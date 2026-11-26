"""Markets (stage M0, docs/backend/07-us-market.md §3, §9): pure rules, no database."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from app.config import CONFIG_PATH, AppConfig
from app.market import (US_NODES, checked_market, market_is_on, move_market_keys, past_stop, resolve_market,
                        stop_after_for)
from app.settings_store import check_config, fill_defaults

NODES = ["locate", "frames", "verify", "confirm", "photos", "plan", "search", "extract", "pricing", "report"]
ORDER = tuple(NODES)


def _resolve(**kw):
    args = dict(user_market=None, is_admin=False, admin_choice=None, country=None, country_map={"US": "us"},
                default="in")
    return resolve_market(**{**args, **kw})


def _file_data() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _old_shape(data: dict) -> dict:
    """config.yaml as it looked before stage M0: India keys in plan / search / extract / pricing, no markets."""
    old = copy.deepcopy(data)
    india = old.pop("markets")["in"]
    old["plan"]["listing_templates"] = india["listing_templates"]
    old["plan"]["new_price_templates"] = india["new_price_templates"]
    old["search"]["country"] = india["search_country"]
    old["extract"]["listing_min_inr"] = india["extract_limits"]["listing_min"]
    old["extract"]["listing_max_inr"] = india["extract_limits"]["listing_max"]
    old["pricing"]["tyre_minor_wear_deduction_inr"] = india["tyre_minor_wear_deduction"]
    for key in ("stop_after_us", "markets_on"):
        old["dev"].pop(key)
    return old


# --- market resolution (order: user pin, admin switch, country header, default) ---

def test_user_pin_wins_over_everything():
    assert _resolve(user_market="us", is_admin=True, admin_choice="in", country="IN", default="in") == "us"


def test_admin_switch_only_for_the_admin():
    assert _resolve(is_admin=True, admin_choice="us") == "us"
    assert _resolve(is_admin=False, admin_choice="us") == "in"


def test_country_header_then_default():
    assert _resolve(country="US") == "us"
    assert _resolve(country=" us ") == "us"
    assert _resolve(country="IN") == "in"
    assert _resolve(country=None, default="us") == "us"


def test_unknown_values_are_skipped():
    assert _resolve(user_market="xx", is_admin=True, admin_choice="zz", country="US",
                    country_map={"US": "mars"}, default="bad") == "in"


def test_checked_market_filter():
    assert checked_market("us") == "us" and checked_market("in") == "in"
    assert checked_market("all") is None and checked_market("") is None and checked_market(None) is None


# --- market on/off and stop per market ---

def test_market_on_off():
    assert market_is_on({"in": True, "us": False}, "in")
    assert not market_is_on({"in": True, "us": False}, "us")
    assert not market_is_on({"in": True}, "us")  # missing = off


def test_stop_setting_of_the_runs_market():
    assert stop_after_for("in", "locate", "upload") == "locate"
    assert stop_after_for("us", "locate", "upload") == "upload"
    assert stop_after_for("us", "locate", "") is None


def test_upload_stop_runs_no_graph_node():
    assert all(past_stop(node, "upload", ORDER) for node in ORDER)
    assert not past_stop("locate", None, ORDER)
    assert past_stop("frames", "locate", ORDER) and not past_stop("locate", "locate", ORDER)
    assert "upload" in US_NODES and "vin_details" in US_NODES


# --- old config versions (before stage M0) ---

def test_old_keys_move_under_markets_in():
    new = _file_data()
    old = _old_shape(new)
    before = copy.deepcopy(old)
    moved = move_market_keys(old)
    assert old == before  # input not changed
    india = moved["markets"]["in"]
    assert india["listing_templates"] == new["markets"]["in"]["listing_templates"]
    assert india["search_country"] == "india"
    assert india["extract_limits"] == {"listing_min": 100000, "listing_max": 10000000}
    assert india["tyre_minor_wear_deduction"] == 5000
    assert india["currency"] == "INR" and india["distance_unit"] == "km"
    assert "listing_templates" not in moved["plan"] and "country" not in moved["search"]
    assert "listing_min_inr" not in moved["extract"] and "tyre_minor_wear_deduction_inr" not in moved["pricing"]


def test_value_already_under_markets_in_wins():
    data = {"plan": {"listing_templates": ["old"]}, "markets": {"in": {"listing_templates": ["new"]}}}
    moved = move_market_keys(data)
    assert moved["markets"]["in"]["listing_templates"] == ["new"] and "listing_templates" not in moved["plan"]


def test_new_shape_is_left_alone():
    data = _file_data()
    assert move_market_keys(data) == data
    assert move_market_keys(None) is None


def test_old_version_loads_with_same_india_values():
    new_cfg = AppConfig(**_file_data())
    old_cfg = AppConfig(**_old_shape(_file_data()))
    assert old_cfg.markets.in_ == new_cfg.markets.in_
    assert old_cfg.dev.markets_on == {"in": True, "us": False}  # default for versions without it
    assert old_cfg.markets.us.currency == "USD"


def test_saved_shape_uses_in_not_in_():
    dumped = AppConfig(**_file_data()).model_dump()
    assert "in" in dumped["markets"] and "in_" not in dumped["markets"]


def test_old_version_passes_the_checks():
    checked, problems = check_config(_old_shape(_file_data()), NODES)
    assert problems == [] and checked["markets"]["in"]["search_country"] == "india"


def test_bad_market_settings_are_refused():
    data = _file_data()
    data["dev"]["stop_after_us"] = "confirm"  # no confirm step for US
    data["markets"]["default"] = "uk"
    data["markets"]["us"]["extract_limits"] = {"listing_min": 500, "listing_max": 100}
    _, problems = check_config(data, NODES)
    fields = {p["field"] for p in problems}
    assert {"dev.stop_after_us", "markets.default", "markets.us.extract_limits"} <= fields


def test_us_upload_stop_is_allowed():
    data = _file_data()
    data["dev"]["stop_after_us"] = "upload"
    assert check_config(data, NODES)[1] == []


# --- new settings at startup: markets.<market>.<field> filled, country_map only as a whole ---

def test_fill_defaults_reaches_market_fields():
    active = {"markets": {"us": {"currency": "USD"}, "country_map": {"US": "us"}}}
    defaults = {"markets": {"us": {"currency": "EUR", "odometer_min_confidence": 0.8},
                            "country_map": {"US": "us", "CA": "us"}}}
    data, added = fill_defaults(active, defaults)
    assert data["markets"]["us"] == {"currency": "USD", "odometer_min_confidence": 0.8}
    assert data["markets"]["country_map"] == {"US": "us"}  # the owner's map is never topped up
    assert added == ["markets.us.odometer_min_confidence"]
