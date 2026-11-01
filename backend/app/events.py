from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

from .runs import events_path, run_dir

_POLL_INTERVAL = 0.5   # seconds between file checks
_KEEPALIVE_SEC = 15    # SSE keep-alive comment interval


async def sse_stream(run_id: str) -> AsyncGenerator[str, None]:
    evpath = events_path(run_id)

    # Replay events already on disk
    if evpath.exists():
        with open(evpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"

    last_pos = evpath.stat().st_size if evpath.exists() else 0
    last_ka = time.monotonic()

    while True:
        await asyncio.sleep(_POLL_INTERVAL)

        now = time.monotonic()
        if now - last_ka >= _KEEPALIVE_SEC:
            yield ": keep-alive\n\n"
            last_ka = now

        if not evpath.exists():
            continue

        try:
            size = evpath.stat().st_size
        except OSError:
            continue

        if size > last_pos:
            with open(evpath, encoding="utf-8") as f:
                f.seek(last_pos)
                chunk = f.read()
            last_pos = size
            for line in chunk.splitlines():
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
