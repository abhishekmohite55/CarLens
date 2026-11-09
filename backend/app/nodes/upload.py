from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
from fastapi import HTTPException, UploadFile

from ..config import get_config
from ..results import save_result
from ..run_index import create_run_row
from ..runs import append_event, create_run

_CHUNK = 1 * 1024 * 1024  # 1 MB


def _fmt_dur(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


async def process_upload(video: UploadFile) -> dict:
    cfg = get_config()

    # Extension check (re-read config so it applies immediately after a yaml edit)
    name = video.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in cfg.upload.allowed_types:
        types_str = ", ".join(t.upper() for t in cfg.upload.allowed_types)
        raise HTTPException(
            400,
            detail={"error": {"code": "invalid_type", "message": f"Only {types_str} videos are accepted."}},
        )

    max_bytes = cfg.upload.max_size_mb * 1024 * 1024
    sha = hashlib.sha256()
    size = 0
    tmp_path: Path | None = None

    try:
        fd, tmp_str = tempfile.mkstemp(suffix=f".{ext}")
        os.close(fd)
        tmp_path = Path(tmp_str)

        with open(tmp_path, "wb") as f:
            while True:
                chunk = await video.read(_CHUNK)
                if not chunk:
                    break
                if size + len(chunk) > max_bytes:
                    raise HTTPException(
                        400,
                        detail={
                            "error": {
                                "code": "too_large",
                                "message": (
                                    f"This file exceeds {cfg.upload.max_size_mb} MB. "
                                    f"The limit is {cfg.upload.max_size_mb} MB."
                                ),
                            }
                        },
                    )
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
            raise HTTPException(
                400,
                detail={"error": {"code": "unreadable", "message": "Could not read the video. It may be corrupted or in an unsupported format."}},
            )

        duration_sec = frame_count / fps
        max_dur = cfg.upload.max_duration_sec
        if duration_sec > max_dur:
            raise HTTPException(
                400,
                detail={
                    "error": {
                        "code": "too_long",
                        "message": f"Video is {_fmt_dur(duration_sec)} long. The limit is {_fmt_dur(max_dur)}.",
                    }
                },
            )

        # runs row first: the primary key guarantees the random id is unique; then the folder
        run_id = create_run_row(sha256=sha.hexdigest(), original_filename=name,
                                size_bytes=size, duration_sec=round(duration_sec, 1))
        run_path = create_run(run_id)
        dest = run_path / f"video.{ext}"
        shutil.move(str(tmp_path), str(dest))
        tmp_path = None  # moved; do not delete in finally

        # meta.json is a node_results row from stage 2.1 (no file in the folder)
        size_bytes = dest.stat().st_size
        meta = {
            "run_id": run_id,
            "original_filename": name,
            "size_bytes": size_bytes,
            "duration_sec": round(duration_sec, 1),
            "sha256": sha.hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        save_result(run_id, "meta.json", meta)

        # Append events (written before they would ever be streamed)
        mb_label = f"{size_bytes / (1024 * 1024):.0f} MB"
        m, s = divmod(int(duration_sec), 60)
        append_event(run_id, "upload", "node_started", {"label": "Upload & check"})
        append_event(run_id, "upload", "packet", {"from": "upload", "to": "locate", "label": f"{mb_label} video"})
        append_event(run_id, "upload", "node_done", {"summary": f"{name}, {mb_label}, {m} min {s} s"})

        return {"run_id": run_id}

    except HTTPException:
        raise
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
