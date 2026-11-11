from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
from fastapi import HTTPException, UploadFile

from ..config import PROJECT_ROOT, get_config
from ..results import save_result
from ..run_index import create_run_row, user_run_with_video
from ..runs import append_event, create_run

_CHUNK = 1 * 1024 * 1024  # 1 MB
_PENDING_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


@dataclass
class Received:
    """An uploaded video that passed the checks, still in a temporary file."""
    path: Path
    name: str
    ext: str
    size: int
    sha256: str
    duration_sec: float


class DuplicateUpload(Exception):
    """Same user, same video (platform step 5, 05-login.md §7.3): the file waits in runs/_pending/ for the choice."""

    def __init__(self, duplicate_of: str, pending_id: str):
        super().__init__("same video")
        self.duplicate_of, self.pending_id = duplicate_of, pending_id


def _fmt_dur(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(400, detail={"error": {"code": code, "message": message}})


async def receive_upload(video: UploadFile) -> Received:
    """Type, size and duration checks; the video is left in a temporary file (deleted on any error)."""
    cfg = get_config()

    # Extension check (re-read config so it applies immediately after a yaml edit)
    name = video.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in cfg.upload.allowed_types:
        types_str = ", ".join(t.upper() for t in cfg.upload.allowed_types)
        raise _bad("invalid_type", f"Only {types_str} videos are accepted.")

    max_bytes = cfg.upload.max_size_mb * 1024 * 1024
    sha = hashlib.sha256()
    size = 0
    fd, tmp_str = tempfile.mkstemp(suffix=f".{ext}")
    os.close(fd)
    tmp_path = Path(tmp_str)
    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = await video.read(_CHUNK)
                if not chunk:
                    break
                if size + len(chunk) > max_bytes:
                    raise _bad("too_large", f"This file exceeds {cfg.upload.max_size_mb} MB. "
                                            f"The limit is {cfg.upload.max_size_mb} MB.")
                sha.update(chunk)
                f.write(chunk)
                size += len(chunk)

        # Duration check via OpenCV
        cap = cv2.VideoCapture(str(tmp_path))
        opened = cap.isOpened()
        fps = cap.get(cv2.CAP_PROP_FPS) if opened else 0.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) if opened else 0.0
        cap.release()
        if not opened or fps <= 0 or frame_count <= 0:
            raise _bad("unreadable", "Could not read the video. It may be corrupted or in an unsupported format.")
        duration_sec = frame_count / fps
        max_dur = cfg.upload.max_duration_sec
        if duration_sec > max_dur:
            raise _bad("too_long", f"Video is {_fmt_dur(duration_sec)} long. The limit is {_fmt_dur(max_dur)}.")
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return Received(tmp_path, name, ext, size, sha.hexdigest(), round(duration_sec, 1))


def start_run(rec: Received, user_id: int | None, spend_token: bool) -> str:
    """runs row (token taken for testers), then the run folder, the video, meta.json and the upload events.
    Raises RunRefused (the file is left where it is; the caller cleans up)."""
    # runs row first: the primary key guarantees the random id is unique; then the folder
    run_id = create_run_row(sha256=rec.sha256, original_filename=rec.name, size_bytes=rec.size,
                            duration_sec=rec.duration_sec, user_id=user_id, spend_token=spend_token)
    run_path = create_run(run_id)
    dest = run_path / f"video.{rec.ext}"
    shutil.move(str(rec.path), str(dest))

    # meta.json is a node_results row from stage 2.1 (no file in the folder)
    size_bytes = dest.stat().st_size
    meta = {
        "run_id": run_id,
        "original_filename": rec.name,
        "size_bytes": size_bytes,
        "duration_sec": rec.duration_sec,
        "sha256": rec.sha256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    save_result(run_id, "meta.json", meta)

    # Append events (written before they would ever be streamed)
    mb_label = f"{size_bytes / (1024 * 1024):.0f} MB"
    m, s = divmod(int(rec.duration_sec), 60)
    append_event(run_id, "upload", "node_started", {"label": "Upload & check"})
    append_event(run_id, "upload", "packet", {"from": "upload", "to": "locate", "label": f"{mb_label} video"})
    append_event(run_id, "upload", "node_done", {"summary": f"{rec.name}, {mb_label}, {m} min {s} s"})
    return run_id


async def process_upload(video: UploadFile, user_id: int, is_admin: bool) -> dict:
    """Upload → new run. Testers: same video again raises DuplicateUpload; one run at a time and 1 token (RunRefused).
    The admin has no limits (dev re-runs)."""
    clean_old_pending()
    rec = await receive_upload(video)
    try:
        if not is_admin:
            old_run = user_run_with_video(user_id, rec.sha256)
            if old_run:
                raise DuplicateUpload(old_run, keep_pending(rec, user_id))
        return {"run_id": start_run(rec, user_id, spend_token=not is_admin)}
    finally:
        rec.path.unlink(missing_ok=True)  # already moved on success; removed on a refusal


# --- same video again: the upload waits in runs/_pending/<id>/ while the user chooses (05-login.md §7.3) ---

def _pending_root() -> Path:
    return PROJECT_ROOT / get_config().paths.runs_dir / "_pending"


def _pending_dir(pending_id: str) -> Path:
    if not _PENDING_ID.match(pending_id):
        raise HTTPException(404, detail={"error": {"code": "not_found", "message": "Upload not found."}})
    return _pending_root() / pending_id


def keep_pending(rec: Received, user_id: int) -> str:
    pending_id = secrets.token_urlsafe(12)
    d = _pending_root() / pending_id
    d.mkdir(parents=True)
    shutil.move(str(rec.path), str(d / f"video.{rec.ext}"))
    info = {"user_id": user_id, "name": rec.name, "ext": rec.ext, "size": rec.size, "sha256": rec.sha256,
            "duration_sec": rec.duration_sec, "kept_at": time.time()}
    (d / "pending.json").write_text(json.dumps(info), encoding="utf-8")
    return pending_id


def _load_pending(pending_id: str, user_id: int) -> tuple[Path, dict]:
    """The kept upload of this user; anyone else's (or an expired one) answers 404."""
    d = _pending_dir(pending_id)
    try:
        info = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = None
    if not info or info["user_id"] != user_id:
        raise HTTPException(404, detail={"error": {"code": "not_found", "message": "Upload not found."}})
    return d, info


def start_pending(pending_id: str, user_id: int) -> dict:
    """"Fresh run" on a kept upload: the normal checks and 1 token."""
    d, info = _load_pending(pending_id, user_id)
    rec = Received(d / f"video.{info['ext']}", info["name"], info["ext"], info["size"], info["sha256"],
                   info["duration_sec"])
    run_id = start_run(rec, user_id, spend_token=True)  # RunRefused leaves the kept file for another try
    shutil.rmtree(d, ignore_errors=True)
    return {"run_id": run_id}


def drop_pending(pending_id: str, user_id: int) -> None:
    """"Open old run": the kept upload is deleted, no token spent."""
    d, _ = _load_pending(pending_id, user_id)
    shutil.rmtree(d, ignore_errors=True)


def clean_old_pending() -> None:
    """Delete kept uploads older than upload.pending_minutes (at every upload and at server start)."""
    root = _pending_root()
    if not root.exists():
        return
    limit = time.time() - get_config().upload.pending_minutes * 60
    for d in root.iterdir():
        try:
            kept_at = json.loads((d / "pending.json").read_text(encoding="utf-8"))["kept_at"]
        except (OSError, ValueError, KeyError):
            kept_at = d.stat().st_mtime
        if kept_at < limit:
            shutil.rmtree(d, ignore_errors=True)

