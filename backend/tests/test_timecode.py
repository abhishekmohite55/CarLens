"""Tests for timecode.mmss_to_seconds and seconds_to_mmss."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.timecode import mmss_to_seconds, seconds_to_mmss


def test_round_trip():
    assert seconds_to_mmss(mmss_to_seconds("01:48.2")) == "01:48.2"


def test_mmss_to_seconds_basic():
    assert mmss_to_seconds("01:48.2") == 108.2


def test_mmss_to_seconds_zero():
    assert mmss_to_seconds("00:09.5") == 9.5


def test_mmss_to_seconds_no_decimal():
    assert mmss_to_seconds("00:09") == 9.0


def test_mmss_to_seconds_rejects_bare_number():
    with pytest.raises(ValueError):
        mmss_to_seconds("105")


def test_mmss_to_seconds_rejects_invalid_seconds():
    with pytest.raises(ValueError):
        mmss_to_seconds("1:60")


def test_mmss_to_seconds_rejects_empty():
    with pytest.raises(ValueError):
        mmss_to_seconds("")


def test_seconds_to_mmss_basic():
    assert seconds_to_mmss(132.7) == "02:12.7"


def test_seconds_to_mmss_zero():
    assert seconds_to_mmss(0.0) == "00:00.0"


def test_seconds_to_mmss_two_digit_minutes():
    assert seconds_to_mmss(600.0) == "10:00.0"
