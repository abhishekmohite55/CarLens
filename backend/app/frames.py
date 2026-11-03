"""Pure OpenCV helpers for frame extraction — no config, no events, no run folders."""
from __future__ import annotations

import time
from pathlib import Path

import cv2


def sample_indices(
    t: float,
    video_fps: float,
    n_frames: int,
    window_sec: float,
    sample_fps: int,
) -> list[int]:
    """Sorted, deduplicated source-frame indices for the window [t-window_sec, t+window_sec)."""
    n_samples = round(2 * window_sec * sample_fps)
    start = t - window_sec
    seen: dict[int, None] = {}
    for k in range(n_samples):
        idx = round((start + k / sample_fps) * video_fps)
        if 0 <= idx < n_frames:
            seen.setdefault(idx, None)
    return sorted(seen.keys())


def sharpness(img, score_scale: float) -> float:
    """Variance of Laplacian on a half-size grayscale copy."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    small = cv2.resize(gray, None, fx=score_scale, fy=score_scale, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(small, cv2.CV_64F).var())


def best_frame(video: Path, indices: list[int], score_scale: float) -> dict:
    """Open one VideoCapture, seek to first index, read forward, return the sharpest frame.

    Returns: frame_index, t (3 dp), sharpness (1 dp), img, frames_extracted, timings_s.
    Raises ValueError if no frame could be read.
    """
    if not indices:
        raise ValueError("no indices to read")

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open {video.name}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        first, last = min(indices), max(indices)
        wanted = set(indices)

        t0 = time.perf_counter()
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        seek_s = time.perf_counter() - t0

        decode_s = score_s = 0.0
        best_img = best_sharp = best_idx = None
        frames_extracted = 0

        for idx in range(first, last + 1):
            t1 = time.perf_counter()
            if idx not in wanted:
                cap.grab()
                decode_s += time.perf_counter() - t1
                continue
            ok, img = cap.read()
            t2 = time.perf_counter()
            decode_s += t2 - t1
            if not ok:
                break
            frames_extracted += 1
            sharp = sharpness(img, score_scale)
            score_s += time.perf_counter() - t2
            if best_img is None or sharp > best_sharp:
                best_img, best_sharp, best_idx = img, sharp, idx

        if best_img is None:
            raise ValueError("no frame could be read")

        total_s = seek_s + decode_s + score_s
        return {
            "frame_index": best_idx,
            "t": round(best_idx / fps, 3),
            "sharpness": round(best_sharp, 1),
            "img": best_img,
            "frames_extracted": frames_extracted,
            "timings_s": {
                "seek": round(seek_s, 3),
                "decode": round(decode_s, 3),
                "score": round(score_s, 3),
                "total": round(total_s, 3),
            },
        }
    finally:
        cap.release()


def save_jpeg(img, path: Path, max_long_edge_px: int, jpeg_quality: int) -> None:
    """Resize to max_long_edge_px (if needed) and save JPEG."""
    h, w = img.shape[:2]
    scale = max_long_edge_px / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
