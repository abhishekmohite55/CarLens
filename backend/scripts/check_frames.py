"""
Dev check: cut frames around the timestamps of saved locate probes and score sharpness.
No Gemini call. Reads runs/_checks/probe_*.json and the original videos in "car video/".

Run from F:\\CarLens\\backend:
    python -m scripts.check_frames                      # every probe_*.json in runs/_checks
    python -m scripts.check_frames probe_20261102_211502_9188.json
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from app.config import get_config
from app.frames import best_frame, sample_indices, save_jpeg
from app.timecode import mmss_to_seconds

PROJECT_ROOT = Path(__file__).parent.parent.parent  # F:\CarLens
CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"
VIDEO_DIR = PROJECT_ROOT / "car video"


def probe_sets(probe_path: Path) -> list[tuple[str, list[dict]]]:
    """Return (set_name, items) for each usable result in a probe file."""
    d = json.loads(probe_path.read_text(encoding="utf-8"))
    if "variants" in d:
        return [
            (f"{probe_path.stem}_{name}", v["parsed"]["items"])
            for name, v in d["variants"].items()
            if v.get("status") == "pass" and v.get("parsed")
        ]
    if d.get("parsed"):
        return [(probe_path.stem, d["parsed"]["items"])]
    return []


def to_seconds(t) -> float:
    return mmss_to_seconds(t) if isinstance(t, str) else float(t)


def run_set(set_name: str, items: list[dict], video_name: str) -> None:
    cfg = get_config()
    fc = cfg.frames
    max_workers = fc.workers or os.cpu_count() or 1  # 0 = CPU count (pool default would be cpu+4)

    video = VIDEO_DIR / video_name
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"  cannot open {video}")
        return
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = n_frames / fps
    cap.release()

    out_dir = CHECKS_DIR / set_name
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    print(f"\n== {set_name}  ({video_name}, {fps:.0f} fps, {duration:.1f} s, "
          f"step {fps / fc.sample_fps:g} frames, {max_workers} threads)")
    print(f"  {'item':<5}{'category':<12}{'t':>9}{'frames':>7}{'seek':>7}{'decode':>8}{'score':>7}{'total':>7}  best")

    def process_item(item: dict) -> dict:
        t = to_seconds(item["t"])
        rec: dict = {"item_id": item["id"], "category": item.get("category"), "label": item.get("label"),
                     "t_text": item["t"], "t": t}
        if not 0 <= t <= duration + 1:
            rec["skipped"] = f"t={t} outside video (0..{duration:.1f})"
            return rec
        indices = sample_indices(t, fps, n_frames, fc.window_sec, fc.sample_fps)
        if not indices:
            rec["skipped"] = "no valid frames in window"
            return rec
        try:
            result = best_frame(video, indices, fc.score_scale)
        except ValueError as exc:
            rec["skipped"] = str(exc)
            return rec
        filename = (f"{item['id']}_{item.get('category')}_"
                    f"{result['t']:06.2f}s_sharp{result['sharpness']:.0f}.jpg")
        save_jpeg(result["img"], out_dir / filename, fc.max_long_edge_px, fc.jpeg_quality)
        rec.update({
            "window": [round(t - fc.window_sec, 3), round(t + fc.window_sec, 3)],
            "frames_extracted": result["frames_extracted"],
            "timings_s": result["timings_s"],
            "sharpest": {"frame_index": result["frame_index"], "t": result["t"],
                         "sharpness": result["sharpness"], "file": filename},
        })
        return rec

    t_all = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        records = list(ex.map(process_item, items))

    for rec in records:
        if "skipped" in rec:
            print(f"  {rec['item_id']:<5}{str(rec['category']):<12}{str(rec['t_text']):>9}  SKIPPED: {rec['skipped']}")
            continue
        tm, best = rec["timings_s"], rec["sharpest"]
        print(f"  {rec['item_id']:<5}{str(rec['category']):<12}{str(rec['t_text']):>9}{rec['frames_extracted']:>7}"
              f"{tm['seek']:>7.2f}{tm['decode']:>8.2f}{tm['score']:>7.2f}{tm['total']:>7.2f}"
              f"  t={best['t']:.2f}s sharp={best['sharpness']:.0f}")

    total_s = round(time.perf_counter() - t_all, 2)
    done = [r for r in records if "skipped" not in r]
    manifest = {
        "probe": set_name, "video": video_name, "source_fps": fps, "duration_sec": round(duration, 2),
        "rule": {"window_sec": fc.window_sec, "sample_fps": fc.sample_fps, "score_scale": fc.score_scale,
                 "max_long_edge_px": fc.max_long_edge_px, "jpeg_quality": fc.jpeg_quality},
        "totals": {"items": len(records), "items_skipped": len(records) - len(done),
                   "frames_extracted": sum(r["frames_extracted"] for r in done),
                   "elapsed_s": total_s, "workers": max_workers},
        "items": records,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  total: {manifest['totals']['frames_extracted']} frames, {total_s} s (incl. JPEG saving) -> {out_dir}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = [CHECKS_DIR / a for a in args] or sorted(CHECKS_DIR.glob("probe_*.json"))
    for p in paths:
        video_name = Path(json.loads(p.read_text(encoding="utf-8"))["video"].replace("\\", "/")).name
        sets = probe_sets(p)
        if not sets:
            print(f"\n== {p.name}: no timestamps, skipped")
        for set_name, items in sets:
            run_set(set_name, items, video_name)


if __name__ == "__main__":
    main()
