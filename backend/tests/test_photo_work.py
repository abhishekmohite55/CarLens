"""Hardening U2: confirm never overtakes a photo upload or removal still in progress."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture
def main_mod(monkeypatch):
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "_photo_work", {})
    monkeypatch.setattr(main_mod, "_confirming", set())
    return main_mod


def test_claim_and_release_count_per_run(main_mod):
    assert main_mod._claim_photo("r_photo0000001") and main_mod._claim_photo("r_photo0000001")
    assert main_mod._photo_work == {"r_photo0000001": 2}
    main_mod._release_photo("r_photo0000001")
    assert main_mod._photo_work == {"r_photo0000001": 1}
    main_mod._release_photo("r_photo0000001")
    assert main_mod._photo_work == {}
    main_mod._release_photo("r_photo0000001")  # an extra release never goes below zero
    assert main_mod._photo_work == {}


def test_no_photo_change_once_confirm_started(main_mod):
    main_mod._confirming.add("r_photo0000002")
    assert not main_mod._claim_photo("r_photo0000002")
    assert main_mod._photo_work == {}
