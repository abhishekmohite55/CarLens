from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


import cv2

from ..config import get_config, pinned
from ..frames import best_frame, sample_indices, save_jpeg
from ..results import delete_results, load_result, save_result
from ..runs import append_event, run_dir

log = logging.getLogger(__name__)

# run_ids with frames in progress (graph run or inspector button); one at a time per run
_running: set[str] = set()
_running_lock = threading.Lock()


def try_claim(run_id: str) -> bool:
    """Mark frames as running for run_id; False if it already is."""
    with _running_lock:
        if run_id in _running:
            return False
        _running.add(run_id)
        return True


def load_locate_items(run_id: str) -> list | None:
    """Locate items from the saved locate response, or None if locate has no valid result."""
    try:
        parsed = (load_result(run_id, "01_locate/response.json") or {}).get("parsed")
    except ValueError:  # an old run's file that is not valid JSON
        return None
    return parsed.get("items") if parsed else None


@pinned
def run_frames(run_id: str, claimed: bool = False) -> None:
    """claimed=True when the caller already holds try_claim(run_id)."""
    if not claimed and not try_claim(run_id):
        log.warning("frames already running for %s; not started again", run_id)
        return
    try:
        append_event(run_id, "frames", "node_started", {"label": "Cutting frames around each timestamp"})
        try:
            _run_frames_inner(run_id)
        except Exception as exc:
            log.exception("run_frames unhandled exception for %s", run_id)
            try:
                append_event(run_id, "frames", "node_failed", {"error": f"Unexpected error: {exc}"})
            except Exception:
                pass
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_frames_inner(run_id: str) -> None:
    rd = run_dir(run_id)

    items = load_locate_items(run_id)
    if items is None:
        append_event(run_id, "frames", "node_skipped", {"reason": "Locate did not finish"})
        return

    # Find original video
    video_path: Path | None = None
    for ext in ("mp4", "mov", "webm"):
        p = rd / f"video.{ext}"
        if p.exists():
            video_path = p
            break
    if video_path is None:
        append_event(run_id, "frames", "node_failed", {"error": "Video file not found in run folder."})
        return

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        append_event(run_id, "frames", "node_failed", {"error": f"Cannot open video: {video_path.name}"})
        return
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = n_frames / fps
    cap.release()

    cfg = get_config()
    fc = cfg.frames

    out_dir = rd / "02_frames"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()
    delete_results(run_id, "frames")  # old manifest row goes with the old JPEGs

    total_items = len(items)
    max_workers = fc.workers or os.cpu_count() or 1  # 0 = CPU count (pool default would be cpu+4)
    wall_start = time.perf_counter()
    records: list[dict | None] = [None] * total_items
    done_count = 0

    def process_item(item_idx: int, item: dict) -> tuple[int, dict]:
        t = item["t"]
        rec: dict = {
            "item_id": item["id"],
            "category": item.get("category"),
            "label": item.get("label"),
            "t_text": item.get("t_text", ""),
            "t": t,
            "window": [round(t - fc.window_sec, 3), round(t + fc.window_sec, 3)],
        }
        try:
            indices = sample_indices(t, fps, n_frames, fc.window_sec, fc.sample_fps)
            if not indices:
                rec["skipped"] = f"t={t} has no valid frames in video"
                return item_idx, rec
            result = best_frame(video_path, indices, fc.score_scale)
            sharp_val = result["sharpness"]
            filename = (f"{item['id']}_{item.get('category')}_"
                        f"{result['t']:06.2f}s_sharp{sharp_val:.0f}.jpg")
            save_jpeg(result["img"], out_dir / filename, fc.max_long_edge_px, fc.jpeg_quality)
            rec.update({
                "frames_extracted": result["frames_extracted"],
                "timings_s": result["timings_s"],
                "sharpest": {
                    "frame_index": result["frame_index"],
                    "t": result["t"],
                    "sharpness": sharp_val,
                    "file": filename,
                },
            })
        except Exception as exc:
            rec["skipped"] = str(exc)
        return item_idx, rec

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i, item in enumerate(items):
            futures[ex.submit(process_item, i, item)] = i

        for future in as_completed(futures):
            item_idx, rec = future.result()
            records[item_idx] = rec
            done_count += 1
            item = items[item_idx]
            if "skipped" in rec:
                msg = f"{item['id']} {item.get('category', '')}: skipped"
            else:
                msg = (f"{item['id']} {item.get('category', '')}: "
                       f"{rec['frames_extracted']} frames, {rec['timings_s']['total']:.2f} s")
            append_event(run_id, "frames", "node_progress", {
                "message": f"{done_count} / {total_items} — {msg}",
                "pct": round(done_count / total_items * 100),
            })

    elapsed_s = round(time.perf_counter() - wall_start, 2)
    done_records = [r for r in records if r is not None and "skipped" not in r]
    skipped_records = [r for r in records if r is not None and "skipped" in r]

    if not done_records and total_items > 0:
        append_event(run_id, "frames", "node_failed", {"error": "No frames could be extracted for any item."})
        return

    total_frames = sum(r["frames_extracted"] for r in done_records)

    manifest = {
        "run_id": run_id,
        "video": video_path.name,
        "source_fps": fps,
        "duration_sec": round(duration_sec, 2),
        "rule": {
            "window_sec": fc.window_sec,
            "sample_fps": fc.sample_fps,
            "score_scale": fc.score_scale,
            "max_long_edge_px": fc.max_long_edge_px,
            "jpeg_quality": fc.jpeg_quality,
        },
        "totals": {
            "items": total_items,
            "items_skipped": len(skipped_records),
            "frames_extracted": total_frames,
            "elapsed_s": elapsed_s,
            "workers": max_workers,
        },
        "items": records,
    }
    save_result(run_id, "02_frames/manifest.json", manifest)  # JPEGs stay files (stage 2.3)

    n = len(done_records)
    jpg_files = [f"02_frames/{r['sharpest']['file']}" for r in done_records]
    append_event(run_id, "frames", "packet", {
        "from": "frames",
        "to": "verify",
        "label": f"{n} frames",
    })
    append_event(run_id, "frames", "node_done", {
        "summary": f"{n} frames kept from {total_frames} scored in {elapsed_s} s",
        "files": ["02_frames/manifest.json"] + jpg_files,
    })
