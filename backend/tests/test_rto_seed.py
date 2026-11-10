"""RTO seed read by migration 0001 (platform stage 2.0)."""
import importlib.util
from pathlib import Path

MIGRATION = Path(__file__).parent.parent / "alembic" / "versions" / "0001_rto.py"


def _read_seed():
    spec = importlib.util.spec_from_file_location("m0001", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.read_seed(mod.SEED)


def test_seed_keeps_every_row_and_one_name_per_state():
    states, rows = _read_seed()
    assert len(states) == 35
    assert len(rows) == 1368
    assert len({s["code"] for s in states}) == 35


def test_seed_keeps_shared_numbers_letter_codes_and_statewide():
    _, rows = _read_seed()
    leh = [r["city"] for r in rows if r["state_code"] == "LA" and r["number"] == "2"]
    assert "Leh" in leh and len(leh) == 4  # one number, several cities
    assert any(r["number"] == "08AA" for r in rows)  # letter codes kept
    assert all(r["statewide"] == r["city"].lower().startswith("statewide") for r in rows)
    assert sum(r["statewide"] for r in rows) == 18
