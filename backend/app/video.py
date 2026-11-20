from __future__ import annotations

import subprocess
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def safe_media_path(path: Path) -> Path:
    """An absolute path for ffmpeg's command line, so it can never be read as an option (hardening S1).
    Raises RuntimeError for a file name that starts with "-"."""
    full = Path(path).resolve()
    if full.name.startswith("-"):
        raise RuntimeError(f"refused file name for ffmpeg: {full.name[:40]!r}")
    return full


def shrink_video(src: Path, dst: Path, *, height: int, fps: int, crf: int, timeout_sec: int | None = None) -> Path:
    """Copy src to dst at reduced height/fps/crf, no audio. Returns dst.
    timeout_sec (hardening A4): ffmpeg is stopped after this long and RuntimeError raised."""
    src_arg, dst_arg = safe_media_path(src), safe_media_path(dst)
    cmd = [
        ffmpeg_exe(), "-v", "error", "-y", "-i", str(src_arg),
        "-vf", f"scale=-2:{int(height)}", "-r", str(int(fps)), "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)),
        str(dst_arg),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:  # subprocess.run kills ffmpeg before raising
        raise RuntimeError(f"took longer than {timeout_sec} s") from exc
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip()[-500:]) from exc
    return dst
