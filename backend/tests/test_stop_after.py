"""config.yaml dev.stop_after: nothing past the named node runs, also when a run starts after it (stage 2.5a)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.graph import END

import app.graph as graph


def _stop(monkeypatch, node):
    monkeypatch.setattr(graph, "get_config", lambda: SimpleNamespace(dev=SimpleNamespace(stop_after=node)))


def test_stops_after_the_named_node(monkeypatch):
    _stop(monkeypatch, "locate")
    assert graph._after({"locate_status": "done"}, "locate", "frames") == END


def test_confirm_by_hand_does_not_start_photos(monkeypatch):
    _stop(monkeypatch, "locate")
    assert graph._entry({"start_at": "photos"}) == END
    _stop(monkeypatch, "confirm")
    assert graph._entry({"start_at": "photos"}) == END
    assert graph._entry({"start_at": "confirm"}) == "confirm"


def test_empty_runs_everything(monkeypatch):
    _stop(monkeypatch, None)
    assert graph._entry({"start_at": "photos"}) == "photos"
    assert graph._after({"plan_status": "done"}, "plan", "search") == "search"
    assert graph._after({"report_status": "done"}, "report", END) == END
    assert graph._after({"plan_status": "failed"}, "plan", "search") == END
