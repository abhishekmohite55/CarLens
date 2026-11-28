"""VIN format check (stage U1, app/vin/check.py): pure."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from app.vin.check import check_digit, is_valid_vin, normalise_vin, vin_problem

REAL = ["1HGCM82643A104332", "1FTFW1ET0DF181960", "5YJSA1E23HF013389", "WBA8E9C54JK542351", "JTDKB20U473794026"]


@pytest.mark.parametrize("vin", REAL)
def test_real_vins_pass(vin):
    assert vin_problem(vin) is None and is_valid_vin(vin)


def test_check_digit_x():
    assert check_digit("1M8GDM9AXKP042788") == "X" and is_valid_vin("1M8GDM9AXKP042788")


def test_normalise():
    assert normalise_vin(" 1hgcm 8264-3a104332 ") == "1HGCM82643A104332"
    assert normalise_vin(None) == ""


def test_messages():
    assert vin_problem("1HGCM8264") == "A VIN has 17 characters (you typed 9)."
    assert "I, O or Q" in vin_problem("1HGCM82643A1O4332")
    assert vin_problem("1HGCM82643A10433*") == "A VIN has only letters and numbers."
    assert "check digit" in vin_problem("1HGCM82653A104332")  # position 9 changed 4 → 5
