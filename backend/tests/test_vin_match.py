"""Video vs VIN check (owner, 27 Nov 2026; app/vin/match.py): pure."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.vin.match import car_line, mismatch_message, vin_match_verdict

CAR = {"make": "HONDA", "model": "Accord", "variant": "EX-V6", "year": 2003, "body": "Coupe", "engine": "3.0L V6",
       "fuel": "Gasoline"}


def test_confident_mismatch_takes_the_action():
    v = vin_match_verdict({"result": "Mismatch", "confidence": 0.9, "reason": "Toyota logo"}, "stop", 0.8)
    assert v["result"] == "mismatch" and v["counted"] and v["action"] == "stop"
    assert vin_match_verdict({"result": "mismatch", "confidence": 0.95}, "warn", 0.8)["action"] == "warn"


def test_unsure_low_confidence_or_missing_never_stops():
    assert vin_match_verdict({"result": "mismatch", "confidence": 0.6}, "stop", 0.8)["action"] == "none"
    assert vin_match_verdict({"result": "mismatch", "confidence": None}, "stop", 0.8)["action"] == "none"
    assert vin_match_verdict({"result": "unsure", "confidence": 0.99}, "stop", 0.8)["action"] == "none"
    assert vin_match_verdict(None, "stop", 0.8) == {"result": "unsure", "confidence": None, "reason": None,
                                                   "frame": None, "counted": False, "action": "none"}
    assert vin_match_verdict({"result": "match", "confidence": 1}, "stop", 0.8)["action"] == "none"
    assert vin_match_verdict({"result": "weird", "confidence": 1}, "stop", 0.8)["result"] == "unsure"


def test_messages():
    assert car_line(CAR) == "2003 HONDA Accord EX-V6, Coupe, 3.0L V6, Gasoline"
    assert car_line(None) == "unknown car"
    msg = mismatch_message(CAR, "Front logo is Toyota.")
    assert msg.startswith("The video does not look like the car of this VIN (2003 HONDA Accord EX-V6")
    assert ": Front logo is Toyota." in msg and msg.endswith("start a new run.")
