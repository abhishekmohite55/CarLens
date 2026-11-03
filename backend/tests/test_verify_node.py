"""409 when 02_frames/manifest.json is missing."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient


def test_verify_409_without_manifest(tmp_path, monkeypatch):
    run_id = "r_20261103_000000_test"
    rd = tmp_path / run_id
    rd.mkdir()
    (rd / "meta.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    import app.runs as runs_mod
    import app.main as main_mod
    monkeypatch.setattr(runs_mod, "run_dir", lambda rid: tmp_path / rid)
    monkeypatch.setattr(main_mod, "run_dir", lambda rid: tmp_path / rid)

    from app.main import app
    client = TestClient(app)
    resp = client.post(f"/api/runs/{run_id}/verify")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_frames_result"
