"""Tests for app/plate.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.plate import is_indian_plate, normalise_plate, pick_plate, plates_in_texts


def test_normalise():
    assert normalise_plate("rj 47-ca.5010") == "RJ47CA5010"


def test_is_indian_plate_valid():
    assert is_indian_plate("RJ47CA5010")
    assert is_indian_plate("MH12AB1234")
    assert is_indian_plate("22BH1234AA")


def test_is_indian_plate_invalid():
    assert not is_indian_plate("SWIFT")
    assert not is_indian_plate("IND")
    assert not is_indian_plate("RJ47CA501")  # only 3 trailing digits


def test_plates_in_texts():
    assert plates_in_texts(["SWIFT", "RJ47 CA5010", "IND"]) == ["RJ47CA5010"]


def test_pick_plate_majority():
    readings = [("RJ47CA5010", 0.95), ("RJ47CA5010", 0.90), ("RJ47CA5011", 0.99)]
    result = pick_plate(readings, 3)
    assert result["text"] == "RJ47CA5010"
    assert result["frames_agree"] == 2
    assert result["frames_tried"] == 3


def test_pick_plate_tie_on_score():
    # tie in count (1 each) → highest mean score wins
    readings = [("MH12AB1234", 0.80), ("RJ47CA5010", 0.95)]
    result = pick_plate(readings, 2)
    assert result["text"] == "RJ47CA5010"


def test_pick_plate_empty():
    assert pick_plate([], 3) is None


def test_pick_plate_confidence():
    readings = [("RJ47CA5010", 0.80), ("RJ47CA5010", 1.00)]
    result = pick_plate(readings, 2)
    # confidence = (2/2) * mean(0.80, 1.00) = 1.0 * 0.90 = 0.90
    assert result["confidence"] == 0.90
