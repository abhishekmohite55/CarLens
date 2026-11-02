from __future__ import annotations

import subprocess
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def shrink_video(src: Path, dst: Path, *, height: int, fps: int, crf: int) -> Path:
    """Copy src to dst at reduced height/fps/crf, no audio. Returns dst."""
    cmd = [
        ffmpeg_exe(), "-v", "error", "-y", "-i", str(src),
        "-vf", f"scale=-2:{height}", "-r", str(fps), "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip()[-500:]) from exc
    return dst
