from app.extract import car_line, domain_of, has_price, render_trimmed, trim_results


def test_has_price():
    assert has_price("Rs. 4.75 Lakh") and has_price("₹1,962.00") and has_price("Rs 800-2,500")
    assert has_price("price 3.5 lakhs") and has_price("2500/-")
    assert not has_price("Founded 2015, website cars24.com") and not has_price(None)


def test_domain_and_car_line():
    assert domain_of("https://www.cardekho.com/used") == "cardekho.com"
    confirm = {"car": {"make": "Hyundai", "model": "i20", "variant": None, "year": 2019, "fuel": "Petrol"},
               "city": "Pune", "odometer_km": 68500}
    assert car_line(confirm) == "Hyundai i20 2019 Petrol · Pune · 68,500 km"


def test_trim_groups_dedupes_caps_and_ids():
    search = {"queries": [
        {"kind": "listing", "for": None, "results": [
            {"url": "https://a.com/1", "title": "A", "content": "₹4.5 lakh", "score": 0.5},
            {"url": "https://b.com/1", "title": "B", "content": "no price here", "score": 0.9}]},
        {"kind": "listing", "for": None, "results": [
            {"url": "https://a.com/1", "title": "A", "content": "₹4.5 lakh", "score": 0.5},
            {"url": "https://c.com/1", "title": "C", "content": "Rs. 5 Lakh", "score": 0.8}]},
        {"kind": "new_price", "for": None, "results": [
            {"url": "https://n.com/1", "title": "N", "content": "on road ₹8.2 lakh", "score": 0.1}]},
        {"kind": "part", "for": "door", "results": [
            {"url": "https://a.com/1", "title": "A", "content": "dent Rs 1,995", "score": 0.4}]}]}
    plan = {"parts": [{"part": "door", "issue": "dent", "severity": "minor", "action": "repair"}]}
    t = trim_results(search, plan, max_per_group=1, max_chars=5)
    assert [g["key"] for g in t["groups"]] == ["listing", "new_price", "door"]
    assert [i["id"] for i in t["groups"][0]["items"]] == ["S1"]          # cap 1, best score (c.com) kept
    assert t["sources"]["S1"]["url"] == "https://c.com/1"
    assert t["sources"]["S2"]["group"] == "new_price"
    assert t["sources"]["S3"]["group"] == "door"                         # same URL allowed in another group
    assert t["groups"][0]["items"][0]["snippet"] == "Rs. 5"              # cut to max_chars
    s = t["stats"]
    assert (s["results_in"], s["dropped_no_price"], s["dropped_duplicate"], s["dropped_over_cap"], s["kept"]) == (6, 1, 1, 1, 3)
    text = render_trimmed("Hyundai i20", t)
    assert text.startswith("CAR: Hyundai i20\n") and "[part door — dent, minor, repair]" in text and "[new price]" in text


from app.extract import check_figures, drop_outliers, group_summary, median_to_max, outlier_values, parse_inr

LIMITS = {"listing_min_inr": 100_000, "listing_max_inr": 10_000_000, "year_tolerance": 1, "outlier_factor": 3}
TRIMMED = {"groups": [
    {"key": "listing", "items": [{"id": "S1", "title": "Used Hyundai Elite i20", "snippet": "2019 Elite i20 ₹4.50 lakh - ₹6.00 lakh; 2013 i20 ₹ 1,90,000"},
                                 {"id": "S2", "title": "Used Swift", "snippet": "Swift ₹4 Lakh"}]},
    {"key": "front_bumper", "items": [{"id": "S3", "title": "i20 parts", "snippet": "Front Bumper ₹1,962.00; lower ₹1,649.00; kit ₹9,000; i20 priced ₹ 6.99 - 11.16 Lakh"}]}],
    "sources": {"S1": {"url": "u1", "group": "listing"}, "S2": {"url": "u2", "group": "listing"},
                "S3": {"url": "u3", "group": "front_bumper"}}}
CAR = {"make": "Hyundai", "model": "i20", "year": 2019}


def test_parse_inr():
    assert parse_inr("₹4.50 lakh") == 450000 and parse_inr("₹ 4,95,000") == 495000
    assert parse_inr("Rs. 1,995") == 1995 and parse_inr("₹28k") == 28000 and parse_inr("₹4.1L") == 410000
    assert parse_inr("Rs.8400*") == 8400 and parse_inr("no number") is None
    assert parse_inr("₹ 6.99 - 11.16 Lakh") == 699000


def test_check_figures_keeps_and_rejects():
    figs = [
        {"source": "S1", "price_text": ["₹4.50 lakh", "₹6.00 lakh"], "about": "this_car", "model_as_written": "Elite i20", "year": 2019},
        {"source": "S1", "price_text": ["₹ 1,90,000"], "about": "this_car", "model_as_written": "i20", "year": 2013},
        {"source": "S2", "price_text": ["₹4 Lakh"], "about": "this_car", "model_as_written": "Swift"},
        {"source": "S3", "price_text": ["₹1,962.00"], "about": "this_item"},
        {"source": "S3", "price_text": ["₹ 6.99 - 11.16 Lakh"], "about": "not_this_item"},
        {"source": "S3", "price_text": ["₹1,962.00", "₹1,649.00", "₹9,000"], "about": "this_item"},
        {"source": "S3", "price_text": ["₹2,500"], "about": "this_item"},
        {"source": "S9", "price_text": ["₹1"], "about": "this_item"},
    ]
    kept, rejected = check_figures(figs, TRIMMED, CAR, LIMITS)
    assert [(k["source"], k["inr"]) for k in kept] == [("S1", [450000, 600000]), ("S3", [1962]), ("S3", [1806, 1962])]
    assert kept[2]["collapsed_from"] == [1649, 1962, 9000] and kept[2]["collapsed_outliers"] == [9000]
    assert [r["reason"] for r in rejected] == ["year 2013 too far from 2019", "model does not match",
                                               "LLM: not this car/item",
                                               "price text not in snippet", "unknown source id"]


def test_owner_example_outliers_then_median_to_max():
    kept, dropped = outlier_values([600000, 500000, 400000, 450000, 53000], 3)
    assert dropped == [53000] and median_to_max(kept) == [475000, 600000]
    assert outlier_values([600000, 53000], 3) == ([600000], [53000])  # works with 2 values


def test_drop_outliers_and_summary():
    figs = [{"group": "g", "inr": [v]} for v in (8000, 8400, 10400, 2987, 60000)]
    kept, dropped = drop_outliers(figs, 3)
    assert sorted(f["inr"][0] for f in kept) == [2987, 8000, 8400, 10400] and dropped[0]["inr"] == [60000]
    assert group_summary(kept) == {"g": {"figures": 4, "min_inr": 2987, "max_inr": 10400}}
    cars = [{"group": "listing", "inr": [v]} for v in (100000, 900000)]
    assert drop_outliers(cars, 3) == (cars, [])                           # car prices: no outlier check
