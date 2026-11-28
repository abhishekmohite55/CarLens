from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from ..config import PROJECT_ROOT, get_config
from ..market import market_is_on
from ..results import save_result
from ..run_index import create_run_row, drop_run_row, log_upload_event, market_off_refusal, user_run_with_video
from ..us_start import confirm_from_vin
from ..runs import append_event, create_run, run_dir
from ..storage import fetch_run, has_video

log = logging.getLogger(__name__)

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


# Hardening A2: uploads being received and checked (copy, hash, OpenCV) right now.
_receiving = 0
_receiving_lock = threading.Lock()


def claim_upload_slot(max_parallel: int | None) -> bool:
    """One more upload may be received; False (nothing counted) when max_parallel are already being received."""
    global _receiving
    with _receiving_lock:
        if max_parallel is not None and _receiving >= max_parallel:
            return False
        _receiving += 1
        return True


def release_upload_slot() -> None:
    global _receiving
    with _receiving_lock:
        _receiving = max(0, _receiving - 1)


def body_too_large(content_length: str | None, max_size_mb: int) -> bool:
    """Hardening A2: the request says it is bigger than any allowed video (+1 MiB for the form around it)."""
    try:
        return int(content_length or 0) > (max_size_mb + 1) * 1024 * 1024
    except ValueError:
        return False


def _write_chunk(f, sha, chunk: bytes) -> None:
    sha.update(chunk)
    f.write(chunk)


def video_duration(path: Path) -> float | None:
    """Seconds, from OpenCV; None when the file is not a readable video."""
    cap = cv2.VideoCapture(str(path))
    opened = cap.isOpened()
    fps = cap.get(cv2.CAP_PROP_FPS) if opened else 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) if opened else 0.0
    cap.release()
    if not opened or fps <= 0 or frame_count <= 0:
        return None
    return frame_count / fps


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
        # S8: file writes, hashing and OpenCV run in a worker thread, never on the server's event loop
        f = await run_in_threadpool(open, tmp_path, "wb")
        try:
            while True:
                chunk = await video.read(_CHUNK)
                if not chunk:
                    break
                if size + len(chunk) > max_bytes:
                    raise _bad("too_large", f"This file exceeds {cfg.upload.max_size_mb} MB. "
                                            f"The limit is {cfg.upload.max_size_mb} MB.")
                await run_in_threadpool(_write_chunk, f, sha, chunk)
                size += len(chunk)
        finally:
            await run_in_threadpool(f.close)

        # Duration check via OpenCV
        duration_sec = await run_in_threadpool(video_duration, tmp_path)
        if duration_sec is None:
            raise _bad("unreadable", "Could not read the video. It may be corrupted or in an unsupported format.")
        max_dur = cfg.upload.max_duration_sec
        if duration_sec > max_dur:
            raise _bad("too_long", f"Video is {_fmt_dur(duration_sec)} long. The limit is {_fmt_dur(max_dur)}.")
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return Received(tmp_path, name, ext, size, sha.hexdigest(), round(duration_sec, 1))


def start_run(rec: Received, user_id: int | None, spend_token: bool, market: str = "in", us: dict | None = None) -> str:
    """runs row (token taken for users), then the run folder, the video, meta.json and the upload events.
    Raises RunRefused (the file is left where it is; the caller cleans up). If anything fails after the row exists,
    the row is removed, the token given back and the video put back where it was (fix 20 Nov)."""
    # runs row first: the primary key guarantees the random id is unique; then the folder
    run_id = create_run_row(sha256=rec.sha256, original_filename=rec.name, size_bytes=rec.size,
                            duration_sec=rec.duration_sec, user_id=user_id, spend_token=spend_token,
                            max_active_runs=get_config().access.max_active_runs if spend_token else None,
                            market=market)
    try:
        _fill_run(run_id, rec, market, us)
    except BaseException:
        _undo_run(run_id, rec, user_id if spend_token else None)
        raise
    return run_id


def _fill_run(run_id: str, rec: Received, market: str = "in", us: dict | None = None) -> None:
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
        "market": market,  # stage M0
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if us:  # stage U2: what the user typed (the car comes from the saved VIN lookup)
        meta.update({k: us["fields"][k] for k in ("vin", "state_code", "state", "miles_user")})
    save_result(run_id, "meta.json", meta)
    car_label = _start_us(run_id, us, meta["created_at"]) if us else None  # before the events: a failure undoes the run

    # Append events (written before they would ever be streamed)
    mb_label = f"{size_bytes / (1024 * 1024):.0f} MB"
    m, s = divmod(int(rec.duration_sec), 60)
    append_event(run_id, "upload", "node_started", {"label": "Upload & check"})
    append_event(run_id, "upload", "packet", {"from": "upload", "to": "locate", "label": f"{mb_label} video"})
    summary = f"{rec.name}, {mb_label}, {m} min {s} s"
    if car_label:  # stage U2
        summary += f"; car from VIN: {car_label}"
    append_event(run_id, "upload", "node_done", {"summary": summary})


def _start_us(run_id: str, us: dict, at: str) -> str:
    """Stage U2: 00_vin/ from the saved lookup and 04_confirm.json from the VIN car, so the run needs no confirm pause.
    Returns the car as one line for the upload summary."""
    lookup = us["lookup"]
    save_result(run_id, "00_vin/request.json", {"node": "vin", "vin": lookup["vin"], "provider": lookup["provider"],
                                               "lookup_id": lookup["lookup_id"], "looked_up_at": lookup["saved_at"]})
    save_result(run_id, "00_vin/response.json", {"provider": lookup["provider"], "ms": lookup["ms"],
                                                "car": lookup["car"], "raw": lookup["raw"]})
    save_result(run_id, "04_confirm.json", confirm_from_vin(us["fields"], lookup["car"], at))
    car = lookup["car"]
    return " ".join(str(car[k]) for k in ("year", "make", "model") if car.get(k)) + f" ({lookup['vin']})"


def _undo_run(run_id: str, rec: Received, refund_user: int | None) -> None:
    """Best effort: every step is tried, a failure here is logged and never hides the first error."""
    run_path = run_dir(run_id)
    try:
        moved = run_path / f"video.{rec.ext}"
        if moved.exists() and not rec.path.exists():
            shutil.move(str(moved), str(rec.path))
    except OSError:
        log.exception("could not put the video back for %s", run_id)
    shutil.rmtree(run_path, ignore_errors=True)
    try:
        drop_run_row(run_id, refund_user)
    except Exception:
        log.exception("could not remove the runs row %s", run_id)


async def process_upload(video: UploadFile, user_id: int, is_admin: bool, market: str = "in",
                         us: dict | None = None) -> dict:
    """Upload → new run. Users: same video again raises DuplicateUpload; one run at a time and 1 token (RunRefused).
    The admin has no limits (dev re-runs). market (stage M0): the run's market, resolved by the caller.
    us (stage U2): {"fields": checked VIN / state / miles, "lookup": the saved VIN lookup} for a US run."""
    await run_in_threadpool(clean_old_pending)
    rec = await receive_upload(video)
    try:
        return await run_in_threadpool(_place_upload, rec, user_id, is_admin, market, us)
    finally:
        rec.path.unlink(missing_ok=True)  # moved on success or when kept; removed on a refusal or a reused video


def _place_upload(rec: Received, user_id: int, is_admin: bool, market: str = "in", us: dict | None = None) -> dict:
    if not is_admin:
        old_run = user_run_with_video(user_id, rec.sha256, market)  # stage U2: a repeat only within the market
        if old_run:
            log_upload_event(user_id, "upload_same_video", {"run_id": old_run})  # hardening A2: admin sees repeats
            raise DuplicateUpload(old_run, keep_pending(rec, user_id, old_run, market, us))
    return {"run_id": start_run(rec, user_id, spend_token=not is_admin, market=market, us=us)}


# --- same video again: the upload waits in runs/_pending/<id>/ while the user chooses (05-login.md §7.3) ---

def _pending_root() -> Path:
    return PROJECT_ROOT / get_config().paths.runs_dir / "_pending"


def _pending_dir(pending_id: str) -> Path:
    if not _PENDING_ID.match(pending_id):
        raise HTTPException(404, detail={"error": {"code": "not_found", "message": "Upload not found."}})
    return _pending_root() / pending_id


def _user_pending(user_id: int) -> list[tuple[Path, dict]]:
    """This user's kept uploads (folder, pending.json)."""
    root = _pending_root()
    out = []
    if root.exists():
        for d in root.iterdir():
            try:
                info = json.loads((d / "pending.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if info.get("user_id") == user_id and not d.name.endswith(_STARTING):  # one being started stays
                out.append((d, info))
    return out


def keep_pending(rec: Received, user_id: int, source_run: str | None = None, market: str = "in",
                 us: dict | None = None) -> str:
    """Same video again (hardening A2, owner 20 Nov): one kept upload per user. The new copy is not stored when the
    earlier run still has the video (here or in S3): the note points to that run and "fresh run" copies from it.
    The same video again only refreshes the note's timer; another video replaces the user's older note."""
    for d, info in _user_pending(user_id):
        if info.get("sha256") == rec.sha256 and info.get("source_run"):
            info["kept_at"] = time.time()
            (d / "pending.json").write_text(json.dumps(info), encoding="utf-8")
            return d.name
        shutil.rmtree(d, ignore_errors=True)
    pending_id = secrets.token_urlsafe(12)
    d = _pending_root() / pending_id
    d.mkdir(parents=True)
    info = {"user_id": user_id, "name": rec.name, "ext": rec.ext, "size": rec.size, "sha256": rec.sha256,
            "duration_sec": rec.duration_sec, "kept_at": time.time(), "market": market, "us": us}
    if source_run and has_video(source_run):
        info["source_run"] = source_run  # the caller deletes the new copy
    else:
        shutil.move(str(rec.path), str(d / f"video.{rec.ext}"))  # earlier video gone: keep this one (as before)
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


def _copy_source_video(d: Path, source_run: str) -> Path:
    """The earlier run's video, copied into the kept-upload folder (fetched back from S3 first when pruned)."""
    fetch_run(source_run, with_video=True)
    videos = sorted(run_dir(source_run).glob("video.*"))
    if not videos:
        raise HTTPException(409, detail={"error": {"code": "video_gone", "message":
                            "The earlier copy of this video is no longer available. Upload it again."}})
    dest = d / videos[0].name
    shutil.copyfile(videos[0], dest)
    return dest


_STARTING = ".start"  # a kept upload being started is renamed <id>.start, so a second click finds nothing


def start_pending(pending_id: str, user_id: int) -> dict:
    """"Fresh run" on a kept upload: the normal checks and 1 token. The kept upload is claimed first (renamed),
    so two clicks at once start one run (fix 20 Nov); on a failure it is put back for another try."""
    d, info = _load_pending(pending_id, user_id)
    market = info.get("market", "in")  # kept uploads from before stage M0 are India
    if not market_is_on(get_config().dev.markets_on, market):
        raise market_off_refusal(market)
    claimed = d.with_name(d.name + _STARTING)
    try:
        d.rename(claimed)
    except OSError:
        raise HTTPException(409, detail={"error": {"code": "already_starting",
                                                   "message": "This upload is already being started."}})
    try:
        path = claimed / f"video.{info['ext']}"
        if not path.exists() and info.get("source_run"):
            path = _copy_source_video(claimed, info["source_run"])
        rec = Received(path, info["name"], path.suffix.lstrip("."), info["size"], info["sha256"], info["duration_sec"])
        run_id = start_run(rec, user_id, spend_token=True, market=market,
                           us=info.get("us"))  # RunRefused leaves the kept file for another try
    except BaseException:
        try:
            claimed.rename(d)
        except OSError:
            log.exception("could not put back a kept upload")  # no request value in the log (Sonar S5145)
        raise
    shutil.rmtree(claimed, ignore_errors=True)
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

