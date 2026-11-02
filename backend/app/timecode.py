from __future__ import annotations

import re

_MMSS_RE = re.compile(r"^(\d{1,2}):(\d{2})(\.\d)?$")


def mmss_to_seconds(text: str) -> float:
    """Convert "MM:SS.s" text to seconds. Raises ValueError for anything else."""
    m = _MMSS_RE.match(text)
    if not m:
        raise ValueError(f"invalid timestamp: {text!r}")
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    tenths = int(m.group(3)[1]) if m.group(3) else 0
    if seconds >= 60:
        raise ValueError(f"invalid timestamp: {text!r}")
    return round(minutes * 60 + seconds + tenths / 10, 1)


def seconds_to_mmss(seconds: float) -> str:
    """Convert seconds to "MM:SS.s" text."""
    total_tenths = round(seconds * 10)
    mm = total_tenths // 600
    remainder = total_tenths % 600
    ss = remainder // 10
    t = remainder % 10
    return f"{mm:02d}:{ss:02d}.{t}"
