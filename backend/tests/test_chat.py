"""Tests for app/llm/chat.py: parse_json and ask_chain with fake models."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.llm.chat import ask_chain, parse_json

VALID = {
    "findings": [{"item_id": "L1", "confirmed": True}],
    "badge": None, "odometer_km": None, "vehicle": None,
    "tyres_assessed": False, "odometer_found": False, "plate": None,
}


def _entry(model="m"):
    e = MagicMock()
    e.provider = "openrouter"
    e.model = model
    return e


def _msg(data: dict):
    m = MagicMock()
    m.text = json.dumps(data)
    m.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "output_token_details": {}}
    return m


def test_parse_json_plain():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_fence_no_lang():
    assert parse_json('```\n{"a": 1}\n```') == {"a": 1}


def test_ask_chain_first_raises_second_answers():
    e1, e2 = _entry("bad"), _entry("good")
    call_n = [0]

    def fake_make(provider, model, temp, timeout, thinking):
        call_n[0] += 1
        m = MagicMock()
        m.invoke = MagicMock(
            side_effect=RuntimeError("503") if call_n[0] == 1 else None,
            return_value=_msg(VALID),
        )
        return m

    with patch("app.llm.chat.make_chat_model", fake_make):
        result = ask_chain([e1, e2], lambda e: [], temperature=0.2, timeout_sec=5,
                           thinking_level=None, validate=lambda p: None,
                           emit=lambda m: None, callbacks=[])
    assert result["answered_by"]["model"] == "good"
    assert len(result["attempts"]) == 2
    assert "error" in result["attempts"][0]


def test_ask_chain_first_hangs_second_answers():
    e1, e2 = _entry("slow"), _entry("fast")

    def fake_make(provider, model, temp, timeout, thinking):
        m = MagicMock()
        if model == "slow":
            def hang(msgs, config=None):
                time.sleep(10)
                return _msg(VALID)
            m.invoke = hang
        else:
            m.invoke = MagicMock(return_value=_msg(VALID))
        return m

    t0 = time.perf_counter()
    with patch("app.llm.chat.make_chat_model", fake_make):
        result = ask_chain([e1, e2], lambda e: [], temperature=0.2, timeout_sec=1,
                           thinking_level=None, validate=lambda p: None,
                           emit=lambda m: None, callbacks=[])
    assert time.perf_counter() - t0 < 5
    assert result["answered_by"]["model"] == "fast"


def test_ask_chain_invalid_answer_tries_next():
    call_n = [0]

    def fake_make(provider, model, temp, timeout, thinking):
        call_n[0] += 1
        m = MagicMock()
        data = {"findings": "not a list"} if call_n[0] == 1 else VALID
        m.invoke = MagicMock(return_value=_msg(data))
        return m

    def validate(p):
        return "bad" if not isinstance(p.get("findings"), list) else None

    with patch("app.llm.chat.make_chat_model", fake_make):
        result = ask_chain([_entry("e1"), _entry("e2")], lambda e: [], temperature=0.2,
                           timeout_sec=5, thinking_level=None, validate=validate,
                           emit=lambda m: None, callbacks=[])
    assert result["answered_by"] is not None
    assert "error" in result["attempts"][0]


def test_ask_chain_all_fail():
    def fake_make(provider, model, temp, timeout, thinking):
        m = MagicMock()
        m.invoke = MagicMock(side_effect=RuntimeError("error"))
        return m

    with patch("app.llm.chat.make_chat_model", fake_make):
        result = ask_chain([_entry("a"), _entry("b")], lambda e: [], temperature=0.2,
                           timeout_sec=5, thinking_level=None, validate=lambda p: None,
                           emit=lambda m: None, callbacks=[])
    assert result["answered_by"] is None
    assert all("error" in a for a in result["attempts"])


def test_ask_chain_applies_normalise_and_records_repairs():
    def fake_make(*a):
        m = MagicMock()
        m.invoke = MagicMock(return_value=_msg([{"item_id": "L1", "confirmed": True}]))
        return m

    def wrap(p):
        return ({"findings": p}, ["wrapped"]) if isinstance(p, list) else (p, [])

    with patch("app.llm.chat.make_chat_model", fake_make):
        result = ask_chain([_entry("m")], lambda e: [], temperature=0.2, timeout_sec=5, thinking_level=None,
                           validate=lambda p: None if isinstance(p, dict) else "not a dict",
                           emit=lambda m: None, callbacks=[], normalise=wrap)
    assert result["answered_by"] == {"provider": "openrouter", "model": "m"}
    assert result["parsed"] == {"findings": [{"item_id": "L1", "confirmed": True}]}
    assert result["attempts"][0]["repairs"] == ["wrapped"]
