"""Tests for timestamp handling in locate._validate_locate_items."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.nodes.locate import _validate_locate_items


def _good_item(**overrides):
    base = {"id": "i1", "category": "plate", "label": "ABC123", "side": "front", "t": "00:10.0"}
    base.update(overrides)
    return base


def test_t_within_duration_passes():
    items = _validate_locate_items([_good_item(t="00:10.0")], duration_sec=132.7)
    assert items[0]["t"] == 10.0
    assert "t_clamped" not in items[0]


def test_t_text_preserved():
    items = _validate_locate_items([_good_item(t="02:12.7")], duration_sec=132.7)
    assert items[0]["t_text"] == "02:12.7"
    assert items[0]["t"] == 132.7


def test_t_equal_duration_passes():
    items = _validate_locate_items([_good_item(t="02:12.7")], duration_sec=132.7)
    assert items[0]["t"] == 132.7


def test_t_1s_past_duration_is_clamped():
    """t = duration + 0.3 (within 1 s window) → clamped to duration, t_clamped True."""
    items = _validate_locate_items([_good_item(t="02:13.0")], duration_sec=132.7)
    assert items[0]["t"] == 132.7
    assert items[0]["t_clamped"] is True


def test_t_at_clamp_boundary_is_clamped():
    """t = duration + 1.0 exactly → still accepted and clamped."""
    items = _validate_locate_items([_good_item(t="02:13.7")], duration_sec=132.7)
    assert items[0]["t"] == 132.7
    assert items[0]["t_clamped"] is True


def test_t_more_than_1s_past_duration_is_rejected():
    with pytest.raises(ValueError, match="out of range"):
        _validate_locate_items([_good_item(t="02:13.8")], duration_sec=132.7)


def test_t_negative_rejected_by_format():
    with pytest.raises(ValueError):
        _validate_locate_items([_good_item(t="-1.0")], duration_sec=132.7)


def test_t_bare_number_rejected():
    with pytest.raises(ValueError):
        _validate_locate_items([_good_item(t="105")], duration_sec=132.7)


def test_t_invalid_seconds_rejected():
    with pytest.raises(ValueError):
        _validate_locate_items([_good_item(t="01:75")], duration_sec=132.7)


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="category"):
        _validate_locate_items([_good_item(category="alien")], duration_sec=132.7)


def test_unknown_side_is_rejected():
    with pytest.raises(ValueError, match="side"):
        _validate_locate_items([_good_item(side="top")], duration_sec=132.7)


def test_does_not_mutate_original_list():
    """Original dicts must be copies so caller's data is not changed."""
    orig = _good_item(t="02:13.0")
    _validate_locate_items([orig], duration_sec=132.7)
    assert "t_clamped" not in orig
