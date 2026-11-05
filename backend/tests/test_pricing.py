from app.pricing import new_price, price_report, repairs, yearly_rates

FIGS = [
    {"group": "new_price", "type": "on_road", "inr": [1_000_000], "source": "S1", "variant": "Asta", "url": "u1"},
    {"group": "new_price", "type": "on_road", "inr": [900_000], "source": "S2", "variant": "Magna", "url": "u2"},
    {"group": "new_price", "type": "ex_showroom", "inr": [800_000], "source": "S3", "url": "u3"},
    {"group": "listing", "type": "single_listing", "inr": [500_000], "year": 2019, "source": "S4", "url": "u4"},
    {"group": "listing", "type": "range", "inr": [400_000, 600_000], "year": 2019, "source": "S5", "url": "u5"},
    {"group": "listing", "type": "single_listing", "inr": [810_000], "year": 2024, "source": "S6", "url": "u6"},
    {"group": "listing", "type": "starting_from", "inr": [300_000], "year": 2019, "source": "S7", "url": "u7"},
    {"group": "listing", "type": "single_listing", "inr": [600_000], "year": 2020, "source": "S10", "url": "u10"},
    {"group": "listing", "type": "single_listing", "inr": [1_200_000], "year": 2023, "source": "S11", "url": "u11"},
    {"group": "front_bumper", "type": "part_price", "inr": [1_000], "source": "S8", "url": "u8"},
    {"group": "front_bumper", "type": "part_price", "inr": [3_000], "source": "S9", "url": "u9"},
]
SETTINGS = {"min_listings_with_year": 3, "tyre_minor_wear_deduction_inr": 5000, "max_from_top": 3}


def test_new_price_prefers_on_road_and_variant():
    assert new_price(FIGS, "asta")["value"] == 1_000_000
    assert new_price(FIGS, None)["value"] == 950_000
    assert new_price([], None) is None


def test_yearly_rates_and_new_price_cap():
    rates, dropped = yearly_rates(FIGS, 1_000_000, 2026)
    assert [x["source"] for x in rates] == ["S4", "S6", "S10"]         # starting_from skipped
    assert abs(rates[0]["rate"] - 0.5 ** (1 / 7)) < 1e-9
    assert [(d["source"], d["reason"]) for d in dropped] == [("S5", "duplicate of S4"),          # same year + price
                                                             ("S11", "at or above new price")]  # ₹12 lakh > ₹10 lakh


def test_repairs_and_report():
    rep = repairs(FIGS, [{"item_id": "L12", "tier": "minor_wear"}, {"item_id": "L6", "tier": "ok"}], 5000)
    assert rep["total"] == 2000 + 5000
    assert rep["items"][0]["note"] == "median of 2 prices; could be up to ₹3,000"
    out = price_report(FIGS, [], {"year": 2019, "variant": "Asta"}, 2026, SETTINGS)
    assert out["status"] == "ok" and out["car_age_years"] == 7
    assert out["fair_value"] == {"median": 500_000, "max": 509_000}       # max = average of the top 3 rates
    assert out["after_repairs"] == {"median": 498_000, "max": 507_000}
    few = price_report(FIGS[:4], [], {"year": 2019}, 2026, SETTINGS)
    assert few["status"] == "unavailable" and "1 listings" in few["reason"]

def test_new_price_exact_variant_beats_contains():
    figs = [{"group": "new_price", "type": "on_road", "inr": [901_000], "source": "A", "variant": "VXi CNG"},
            {"group": "new_price", "type": "on_road", "inr": [723_000], "source": "B", "variant": "VXI"}]
    np = new_price(figs, "VXi")
    assert np["value"] == 723_000 and np["variant_match"] == "exact"
    np = new_price(figs[:1], "VXi")                                     # no exact name: loose match is the fallback
    assert np["value"] == 901_000 and np["variant_match"] == "contains"


def test_yearly_rates_min_age():
    rates, dropped = yearly_rates(FIGS, 1_000_000, 2026, min_age=3)
    assert [x["source"] for x in rates] == ["S4", "S10"]                # S6 (2024, age 2) too young
    assert ("S6", "under 3 years old") in [(d["source"], d["reason"]) for d in dropped]
