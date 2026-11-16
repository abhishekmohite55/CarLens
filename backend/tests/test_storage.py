"""Step 8.1: run files on S3 (app/storage.py) against a fake bucket kept in a temp folder (no AWS, no moto)."""
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.storage as storage

BUCKET = "carlens-runs-test"
RUN = "r_s3_test_0001"


class _Paginator:
    def __init__(self, fake):
        self.fake = fake

    def paginate(self, Bucket, Prefix):
        assert Bucket == BUCKET
        root = self.fake.root
        contents = []
        for p in sorted(root.rglob("*")):
            key = p.relative_to(root).as_posix()
            if p.is_file() and key.startswith(Prefix):
                modified = datetime.fromtimestamp(int(self.fake.modified[key]), tz=timezone.utc)  # whole seconds
                contents.append({"Key": key, "Size": p.stat().st_size, "LastModified": modified})
        yield {"Contents": contents} if contents else {}


class FakeS3:
    """The few boto3 S3 calls storage.py makes; objects are files under root."""

    def __init__(self, root: Path):
        self.root = root
        self.modified: dict[str, float] = {}
        self.uploads: list[str] = []
        self.downloads: list[str] = []
        self.fail = False

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        if self.fail:
            raise RuntimeError("S3 down")
        return _Paginator(self)

    def upload_file(self, filename, bucket, key):
        assert bucket == BUCKET
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(filename, target)
        self.modified[key] = time.time()
        self.uploads.append(key)

    def download_file(self, bucket, key, filename):
        assert bucket == BUCKET
        shutil.copyfile(self.root / key, filename)
        self.downloads.append(key)

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            (self.root / obj["Key"]).unlink(missing_ok=True)
            self.modified.pop(obj["Key"], None)


@pytest.fixture
def s3(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    fake = FakeS3(tmp_path / "bucket")
    fake.root.mkdir()
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setattr(storage, "_client", fake)
    monkeypatch.setattr(storage, "run_dir", lambda rid: runs / rid)
    monkeypatch.setattr(storage, "_runs_root", lambda: runs)
    storage._pushed.clear()
    fake.runs = runs
    return fake


def _make_run(runs: Path, run_id: str = RUN, finished: bool = True) -> Path:
    d = runs / run_id
    (d / "02_frames").mkdir(parents=True)
    (d / "video.mp4").write_bytes(b"v" * 100)
    (d / "02_frames" / "f1.jpg").write_bytes(b"jpg")
    last = {"node": "pipeline", "type": "run_done"} if finished else {"node": "confirm", "type": "node_started"}
    (d / "events.jsonl").write_text(json.dumps({"node": "upload", "type": "node_done"}) + "\n"
                                    + json.dumps(last) + "\n", encoding="utf-8")
    return d


def _age(folder: Path, days: float) -> None:
    old = time.time() - days * 86400
    for p in folder.rglob("*"):
        os.utime(p, (old, old))


def test_off_without_bucket(tmp_path, monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setattr(storage, "_client", None)
    storage.push_run(RUN)
    storage.fetch_run(RUN, with_video=True)
    storage.delete_run_files(RUN)
    assert storage.prune_local() == []
    assert storage._client is None  # boto3 never loaded


def test_push_uploads_everything_then_only_changes(s3):
    d = _make_run(s3.runs)
    storage.push_run(RUN)
    assert sorted(s3.uploads) == [f"runs/{RUN}/02_frames/f1.jpg", f"runs/{RUN}/events.jsonl", f"runs/{RUN}/video.mp4"]

    s3.uploads.clear()
    (d / "03_verify").mkdir()
    (d / "03_verify" / "response.json").write_text("{}", encoding="utf-8")
    storage.push_run(RUN)
    assert sorted(s3.uploads) == [f"runs/{RUN}/03_verify/response.json", f"runs/{RUN}/events.jsonl"]


def test_push_after_restart_skips_files_already_in_s3(s3):
    _make_run(s3.runs)
    storage.push_run(RUN)
    storage._pushed.clear()  # a new server process
    s3.uploads.clear()
    storage.push_run(RUN)
    assert s3.uploads == [f"runs/{RUN}/events.jsonl"]


def test_push_error_is_logged_not_raised(s3, caplog):
    _make_run(s3.runs)
    s3.fail = True
    storage.push_run(RUN)
    assert "S3 push failed" in caplog.text


def test_fetch_without_then_with_video(s3):
    d = _make_run(s3.runs)
    storage.push_run(RUN)
    shutil.rmtree(d)

    storage.fetch_run(RUN)
    assert (d / "02_frames" / "f1.jpg").read_bytes() == b"jpg"
    assert (d / "events.jsonl").exists()
    assert not (d / "video.mp4").exists()

    storage.fetch_run(RUN)  # folder here: nothing listed or fetched again
    assert len(s3.downloads) == 2

    storage.fetch_run(RUN, with_video=True)
    assert (d / "video.mp4").read_bytes() == b"v" * 100
    assert len(s3.downloads) == 3

    s3.uploads.clear()
    storage._pushed.clear()
    storage.push_run(RUN)  # fetched files have their S3 age: not sent back
    assert s3.uploads == [f"runs/{RUN}/events.jsonl"]


def test_fetch_unknown_run_makes_no_folder(s3):
    storage.fetch_run("r_missing")
    assert not (s3.runs / "r_missing").exists()


def test_delete_run_files(s3):
    _make_run(s3.runs)
    storage.push_run(RUN)
    storage.delete_run_files(RUN)
    assert not any(p.is_file() for p in s3.root.rglob("*"))


def test_prune_keeps_new_unfinished_and_unsynced_runs(s3):
    old = _make_run(s3.runs, "r_old_done")
    _age(old, 8)
    new = _make_run(s3.runs, "r_new_done")
    _age(new, 1)
    waiting = _make_run(s3.runs, "r_old_waiting", finished=False)
    _age(waiting, 8)

    assert storage.prune_local(keep_days=7) == ["r_old_done"]  # pushed first, then deleted
    assert not old.exists() and new.exists() and waiting.exists()
    assert (s3.root / "runs" / "r_old_done" / "video.mp4").exists()

    s3.fail = True  # S3 not reachable: nothing is deleted
    _age(new, 8)
    assert storage.prune_local(keep_days=7) == []
    assert new.exists()
