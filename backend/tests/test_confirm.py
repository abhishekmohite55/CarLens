from app.confirm import build_record, city_from_plate, needs_expand, prefill, year_options

RTO = [
    {"state_code": "MH", "number": 12, "state": "Maharashtra", "city": "Pune"},
    {"state_code": "MH", "number": 14, "state": "Maharashtra", "city": "Pimpri-Chinchwad"},
    {"state_code": "AP", "number": 39, "state": "Andhra Pradesh", "city": "Statewide (current series)"},
    {"state_code": "AP", "number": 2, "state": "Andhra Pradesh", "city": "Ananthapuramu"},
]


def test_city_full_code():
    c = city_from_plate("MH12AB1234", ["MH14AB1234"], RTO)
    assert c["value"] == "Pune" and c["state"] == "Maharashtra"
    assert [x["code"] for x in c["candidates"]] == ["MH12", "MH14"]


def test_city_statewide_gives_state_cities():
    c = city_from_plate("AP39AB1234", [], RTO)
    assert c["value"] is None and c["state"] == "Andhra Pradesh"
    assert [x["city"] for x in c["candidates"]] == ["Ananthapuramu"]


def test_city_no_plate():
    assert city_from_plate(None, [], RTO) == {"value": None, "state": None, "candidates": []}


def test_year_options():
    opts = year_options(2017, 8, 2026)
    assert opts[0] == 2025 and opts[-1] == 2009 and 2022 in opts
    assert year_options(2024, 8, 2026)[0] == 2026
    assert len(year_options(None, 8, 2026)) == 17


def test_needs_expand_ignores_variant():
    ok = {"value": "x", "confidence": 0.9}
    v = {"make": ok, "model": ok, "year": {"value": 2017, "confidence": 0.9}, "variant": {"value": None, "confidence": 0.1}}
    assert needs_expand(v, 0.6) is False
    v["year"] = {"value": 2017, "confidence": 0.5}
    assert needs_expand(v, 0.6) is True


def test_build_record_changed():
    payload = {"vehicle": {"make": {"value": "Maruti Suzuki"}, "model": {"value": "Swift"}, "year": {"value": 2017}},
               "plate": {"text": "MH12AB1234"}, "city": {"value": "Pune", "state": "Maharashtra"},
               "odometer_km": {"value": 40003}}
    answer = {**prefill(payload), "skipped": ["tyre_photo"]}
    answer["car"] = {**answer["car"], "year": 2022, "variant": "VXi"}
    rec = build_record(payload, answer)
    assert rec["changed"] == ["variant", "year"]
    assert rec["skipped"] == ["tyre_photo"] and rec["photos"] == []
