"""Run files on S3 (platform step 8.1, docs/platform/08-1-s3-runs.md).

S3 is on only when the env var S3_BUCKET is set; without it every function here does nothing, so a laptop run
works as before. Layout: s3://<S3_BUCKET>/runs/<run_id>/<path inside the run folder>.

- push_run: after the upload and after every node; uploads files that are new or changed (events.jsonl always).
- fetch_run: when a run is opened and its folder is not on this server (pruned); the video only when asked.
- delete_run_files: the admin deleted the run.
- prune_local: nightly (python -m app.storage prune); deletes the server copy of finished runs untouched for
  storage.local_keep_days, only when S3 holds every file.

S3 errors are logged and never stop a run.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from .config import PROJECT_ROOT, get_config
from .run_index import is_run_id
from .runs import run_dir

log = logging.getLogger(__name__)

PREFIX = "runs"
_EVENTS = "events.jsonl"

_client = None
_client_lock = threading.Lock()
_run_locks: dict[str, threading.Lock] = {}
_run_locks_lock = threading.Lock()
_pushed: dict[str, dict[str, tuple[int, int]]] = {}  # run id -> {path: (size, mtime_ns)} sent by this process
_SLACK_SEC = 2  # S3 LastModified has whole seconds; a file written just before its upload is not "changed"


def bucket() -> str:
    return os.environ.get("S3_BUCKET", "").strip()


def enabled() -> bool:
    return bool(bucket())


def _s3():
    """boto3 S3 client; credentials come from the EC2 instance role (no keys in .env)."""
    global _client
    with _client_lock:
        if _client is None:
            import boto3  # imported here: a laptop without S3_BUCKET never needs it
            _client = boto3.client("s3")
        return _client


def _run_lock(run_id: str) -> threading.Lock:
    with _run_locks_lock:
        return _run_locks.setdefault(run_id, threading.Lock())


def _key(run_id: str, rel: str) -> str:
    return f"{PREFIX}/{run_id}/{rel}"


def _is_video(rel: str) -> bool:
    return "/" not in rel and rel.startswith("video.")


def _remote(run_id: str) -> dict[str, dict]:
    """{path inside the run folder: {"size", "modified" (epoch seconds)}} of the run's objects in S3."""
    out: dict[str, dict] = {}
    start = f"{PREFIX}/{run_id}/"
    for page in _s3().get_paginator("list_objects_v2").paginate(Bucket=bucket(), Prefix=start):
        for obj in page.get("Contents", []):
            out[obj["Key"][len(start):]] = {"size": obj["Size"], "modified": obj["LastModified"].timestamp()}
    return out


def _is_temp(rel: str) -> bool:
    """A file still being written (video_small.part.mp4, fetch's *.part): never copied either way."""
    return ".part" in rel.rsplit("/", 1)[-1]


def _local(folder: Path) -> dict[str, os.stat_result]:
    return {rel: p.stat() for p in folder.rglob("*")
            if p.is_file() and not p.is_symlink() and not _is_temp(rel := p.relative_to(folder).as_posix())}


def _changed(run_id: str, rel: str, st: os.stat_result, remote: dict | None) -> bool:
    if remote is None or rel == _EVENTS:
        return True
    sent = _pushed.get(run_id, {}).get(rel)
    if sent is not None:  # this process uploaded it: exact check
        return sent != (st.st_size, st.st_mtime_ns)
    return st.st_size != remote["size"] or st.st_mtime > remote["modified"] + _SLACK_SEC


def push_run(run_id: str) -> None:
    """Copy the run's new and changed files to S3. Never raises."""
    if not enabled():
        return
    folder = run_dir(run_id)
    if not folder.is_dir():
        return
    with _run_lock(run_id):
        try:
            remote = _remote(run_id)
            for rel, st in _local(folder).items():
                if _changed(run_id, rel, st, remote.get(rel)):
                    _s3().upload_file(str(folder / rel), bucket(), _key(run_id, rel))
                    _pushed.setdefault(run_id, {})[rel] = (st.st_size, st.st_mtime_ns)
        except Exception as exc:  # noqa: BLE001  S3 down or no access: the run goes on
            log.warning("S3 push failed for run %s: %s", run_id, exc)


def fetch_run(run_id: str, with_video: bool = False) -> None:
    """Bring a pruned run back from S3 (the video only with with_video). Never raises.
    A run folder on this server is the newest copy: nothing is fetched while it is here (and has the video)."""
    if not enabled() or not is_run_id(run_id):  # hardening S14: never a key or log line from a bad id
        return
    folder = run_dir(run_id)
    if folder.is_dir() and (not with_video or any(folder.glob("video.*"))):
        return
    with _run_lock(run_id):
        try:
            for rel, obj in _remote(run_id).items():
                target = folder / rel
                if target.exists() or _is_temp(rel) or (_is_video(rel) and not with_video):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".part")
                _s3().download_file(bucket(), _key(run_id, rel), str(tmp))
                os.utime(tmp, (obj["modified"], obj["modified"]))  # same age as in S3: not pushed again
                os.replace(tmp, target)
        except Exception as exc:  # noqa: BLE001
            log.warning("S3 fetch failed for run %s: %s", run_id, exc)


def has_video(run_id: str) -> bool:
    """Hardening A2: the run's video is still here or in S3 (a same-video upload can then reuse it). Never raises."""
    if not is_run_id(run_id):
        return False
    if any(run_dir(run_id).glob("video.*")):
        return True
    if not enabled():
        return False
    try:
        return any(_is_video(rel) for rel in _remote(run_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("S3 check failed: %s", exc)
        return False


def delete_run_files(run_id: str) -> None:
    """Delete the run's objects in S3 (admin deleted the run). Never raises."""
    if not enabled() or not is_run_id(run_id):  # hardening S14
        return
    _pushed.pop(run_id, None)
    try:
        keys = [_key(run_id, rel) for rel in _remote(run_id)]
        for i in range(0, len(keys), 1000):  # delete_objects takes at most 1000 keys
            _s3().delete_objects(Bucket=bucket(), Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
    except Exception as exc:  # noqa: BLE001
        log.warning("S3 delete failed for run %s: %s", run_id, exc)


def _finished(folder: Path) -> bool:
    """The last event is the pipeline's run_done: nothing is running or waiting at confirm."""
    try:
        lines = [ln for ln in (folder / _EVENTS).read_text(encoding="utf-8").splitlines() if ln.strip()]
        last = json.loads(lines[-1]) if lines else {}
    except (OSError, ValueError):
        return False
    return last.get("node") == "pipeline" and last.get("type") == "run_done"


def _runs_root() -> Path:
    return PROJECT_ROOT / get_config().paths.runs_dir


def prune_local(now: float | None = None, keep_days: int | None = None) -> list[str]:
    """Delete the server copy of finished runs untouched for keep_days (default storage.local_keep_days), when S3
    holds every file. Returns the pruned run ids."""
    if not enabled():
        return []
    root = _runs_root()
    if not root.is_dir():
        return []
    days = keep_days if keep_days is not None else get_config().storage.local_keep_days
    cutoff = (now or time.time()) - days * 86400
    pruned = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        run_id = folder.name
        files = _local(folder)
        if not files or max(st.st_mtime for st in files.values()) > cutoff or not _finished(folder):
            continue
        push_run(run_id)
        try:
            remote = _remote(run_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("S3 list failed for run %s, kept: %s", run_id, exc)
            continue
        missing = [rel for rel, st in files.items() if remote.get(rel, {}).get("size") != st.st_size]
        if missing:
            log.warning("run %s kept: %d file(s) not in S3 (%s)", run_id, len(missing), missing[0])
            continue
        shutil.rmtree(folder, ignore_errors=True)
        _pushed.pop(run_id, None)
        pruned.append(run_id)
    return pruned


if __name__ == "__main__":
    if sys.argv[1:] != ["prune"]:
        sys.exit("usage: python -m app.storage prune")
    logging.basicConfig(level=logging.INFO)
    if not enabled():
        sys.exit("S3_BUCKET is not set; nothing pruned")
    done = prune_local()
    print(f"pruned {len(done)} run(s): {', '.join(done) or '-'}")
