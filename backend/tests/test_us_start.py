"""US run start (stage U2) and miles rule (stage U3): pure rules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from app.miles import miles_used, reading_in_miles
from app.nodes.verify import normalise_us_answer, validate_answer
from app.us_start import UsFieldError, check_us_fields, confirm_from_vin, parse_miles

HONDA = "1HGCM82643A104332"


def _check(vin=HONDA, state="ca", miles="48,200"):
    return check_us_fields(vin, state, miles, miles_min=1, miles_max=999_999)


def test_fields_ok():
    assert _check() == {"vin": HONDA, "state_code": "CA", "state": "California", "miles_user": 48200}
    assert _check(state="")["state"] is None and _check(state=None)["state_code"] is None


@pytest.mark.parametrize("kw,code", [
    ({"vin": ""}, "vin_invalid"), ({"vin": "1HGCM82653A104332"}, "vin_invalid"),
    ({"state": "XX"}, "state_invalid"),
    ({"miles": ""}, "miles_invalid"), ({"miles": "48.2k"}, "miles_invalid"), ({"miles": "0"}, "miles_invalid"),
    ({"miles": "1,000,000"}, "miles_invalid"), ({"miles": "-5"}, "miles_invalid"),
])
def test_fields_refused(kw, code):
    with pytest.raises(UsFieldError) as e:
        _check(**kw)
    assert e.value.code == code and e.value.message


def test_parse_miles():
    assert parse_miles("48,200") == 48200 and parse_miles(" 48200 ") == 48200
    assert parse_miles("48,20") is None and parse_miles("4,8200") is None and parse_miles("") is None


def test_confirm_from_vin_has_indias_shape():
    car = {"make": "HONDA", "model": "Accord", "variant": "EX-V6", "year": 2003, "fuel": "Gasoline", "body": "Coupe",
           "engine": "3.0L V6", "drive": None}
    record = confirm_from_vin(_check(), car, "2026-11-26T10:00:00Z")
    for key in ("car", "plate", "city", "state", "odometer_km", "changed", "skipped", "photos", "confirmed_at"):
        assert key in record
    assert record["car"]["model"] == "Accord" and record["state"] == "California" and record["plate"] is None
    assert record["vin"] == HONDA and record["miles_user"] == 48200 and record["source"] == "vin"


def test_miles_higher_of_two():
    r = miles_used(48200, 52310, "mi", 0.9, 0.8)
    assert r["miles_used"] == 52310 and r["source"] == "odometer" and r["accepted"]
    r = miles_used(60000, 52310, "mi", 0.9, 0.8)
    assert r["miles_used"] == 60000 and r["source"] == "you" and r["accepted"]


def test_miles_low_confidence_or_no_reading():
    r = miles_used(48200, 99999, "mi", 0.5, 0.8)
    assert r["miles_used"] == 48200 and not r["accepted"] and "below" in r["why"]
    r = miles_used(48200, None, None, None, 0.8)
    assert r["miles_used"] == 48200 and r["reading_miles"] is None and r["why"] == "no odometer reading"


def test_km_reading_converted():
    assert reading_in_miles(100000, "km") == 62137
    r = miles_used(50000, 100000, "km", 0.9, 0.8)
    assert r["miles_used"] == 62137 and r["source"] == "odometer"


def test_us_verify_answer_shape():
    parsed, repairs = normalise_us_answer({"findings": [{"item_id": "L1", "confirmed": True}, {"x": 1}],
                                           "odometer": {"text": "48210", "unit": "Miles", "confidence": 0.9}})
    assert parsed["odometer"] == {"value": "48210", "unit": "mi", "confidence": 0.9}
    assert parsed["tyres_assessed"] is None and len(parsed["findings"]) == 1 and validate_answer(parsed) is None
    assert "plate" not in parsed and "vehicle" not in parsed
    wrapped, _ = normalise_us_answer({"findings": [], "odometer": 52000})
    assert wrapped["odometer"] == {"value": 52000, "unit": None, "confidence": None}
    clean = {"findings": [], "odometer": {"value": 1, "unit": "mi", "confidence": 1}, "tyres_assessed": True,
             "odometer_found": True, "vin_match": {"result": "match", "confidence": 0.9}}
    assert normalise_us_answer(dict(clean))[1] == []


def test_vin_match_text_is_wrapped():
    parsed, _ = normalise_us_answer({"findings": [], "vin_match": "mismatch"})
    assert parsed["vin_match"] == {"result": "mismatch", "confidence": None}
