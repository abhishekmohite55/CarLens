"""vPIC answers → the common shape (stage U1, app/vin/mapping.py): real answers saved from vPIC (tests/fixtures/vin)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import VPIC_FIELDS
from app.vin.mapping import engine_text, not_found_message, pick, to_common
from app.vin.providers import vpic

FIXTURES = Path(__file__).parent / "fixtures" / "vin"


def _common(vin):
    raw = json.loads((FIXTURES / f"{vin}.vpic.json").read_text(encoding="utf-8"))
    return to_common(vin, "vpic", pick(vpic.record(raw), VPIC_FIELDS))


def test_honda_accord():
    a = _common("1HGCM82643A104332")
    assert a["ok"] and a["error"] is None and a["provider"] == "vpic"
    assert a["car"] == {"make": "HONDA", "model": "Accord", "variant": "EX-V6", "year": 2003, "fuel": "Gasoline",
                        "body": "Coupe", "engine": "3.0L V6", "drive": None}


def test_ford_f150_without_trim():
    car = _common("1FTFW1ET0DF181960")["car"]
    assert car["model"] == "F-150" and car["variant"] is None and car["engine"] == "3.5L V6"
    assert car["drive"] == "4WD/4-Wheel Drive/4x4"


def test_tesla_is_electric():
    a = _common("5YJSA1E23HF013389")
    assert a["ok"] and a["car"]["engine"] == "Electric" and a["car"]["year"] == 2017


def test_bmw_without_model_is_not_found():
    a = _common("WBA8E9C54JK542351")
    assert not a["ok"] and a["error"] == "not_found" and a["car"]["make"] == "BMW"
    assert "2018 BMW but not its model" in not_found_message(a["car"])
    assert not_found_message({}) == "We could not find a car for this VIN. Check the number."


def test_engine_text():
    assert engine_text("1.8", "4", "In-Line", "Gasoline") == "1.8L I4"
    assert engine_text("2.0", "4", None, None) == "2.0L 4 cyl"
    assert engine_text(None, None, None, None) is None


def test_dotted_paths_for_nested_answers():
    assert pick({"vehicle": {"make": "HONDA"}, "x": "Not Applicable"}, {"make": "vehicle.make", "body": "x"}) == \
        {"make": "HONDA", "body": None}
