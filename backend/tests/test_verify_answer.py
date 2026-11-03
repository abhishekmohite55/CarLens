"""normalise_answer / validate_answer: repair known model slips, never change a well-formed answer."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.nodes.verify import normalise_answer, validate_answer

PROMPT = Path(__file__).parent.parent.parent / "prompts" / "verify.system.md"


def _prompt_example() -> dict:
    """The exact JSON example in prompts/verify.system.md (a well-formed answer)."""
    text = PROMPT.read_text(encoding="utf-8")
    start = text.index('{\n  "findings"')
    end = text.index("The file names")
    return json.loads(text[start:end])


def test_well_formed_answer_is_unchanged():
    answer = _prompt_example()
    before = copy.deepcopy(answer)
    out, repairs = normalise_answer(answer)
    assert out == before
    assert repairs == []
    assert validate_answer(out) is None


def test_nemotron_value_keys_renamed():
    # Real Nemotron answer, 3 Nov 2026: plate.value / badge.value instead of .text
    answer = _prompt_example()
    answer["plate"] = {"value": "RJ47CA5010", "confidence": 0.95, "alternatives": [], "frame": "L2.jpg"}
    answer["badge"] = {"value": "SWIFT", "confidence": 0.9, "frame": "L7.jpg"}
    out, repairs = normalise_answer(answer)
    assert out["plate"]["text"] == "RJ47CA5010" and "value" not in out["plate"]
    assert out["badge"]["text"] == "SWIFT"
    assert len(repairs) == 2


def test_list_answer_becomes_findings():
    out, repairs = normalise_answer([{"item_id": "L2", "confirmed": True}])
    assert out["findings"] == [{"item_id": "L2", "confirmed": True}]
    assert out["plate"] is None and out["vehicle"] is None and out["tyres_assessed"] is None
    assert validate_answer(out) is None
    assert repairs[0].startswith("answer was a list")


def test_bare_values_wrapped():
    answer = _prompt_example()
    answer["plate"] = "RJ47CA5010"
    answer["odometer_km"] = 40003
    answer["vehicle"]["make"] = "Maruti Suzuki"
    out, _ = normalise_answer(answer)
    assert out["plate"] == {"text": "RJ47CA5010", "confidence": None}
    assert out["odometer_km"] == {"value": 40003, "confidence": None}
    assert out["vehicle"]["make"] == {"value": "Maruti Suzuki", "confidence": None, "alternatives": []}
    assert out["plate"]["text"]  # the node can now add plate["source"] safely


def test_missing_keys_filled_and_bad_findings_dropped():
    out, repairs = normalise_answer({"findings": [{"item_id": "L2", "confirmed": False, "reason": "r"},
                                                  "L3 looks fine", {"confirmed": True}]})
    assert [f["item_id"] for f in out["findings"]] == ["L2"]
    assert all(out[k] is None for k in ("plate", "badge", "odometer_km", "vehicle", "tyres_assessed", "odometer_found"))
    assert any("2 finding(s)" in r for r in repairs)
    assert validate_answer(out) is None


def test_unrepairable_answers_rejected():
    assert validate_answer(normalise_answer("just text")[0]) == "answer is not a JSON object"
    assert validate_answer(normalise_answer({"plate": None})[0]) == "findings is missing or not a list"
    assert validate_answer(normalise_answer({"findings": "none"})[0]) == "findings is missing or not a list"
