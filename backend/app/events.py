from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

from .runs import events_path, run_dir

_POLL_INTERVAL = 0.5   # seconds between file checks
_KEEPALIVE_SEC = 15    # SSE keep-alive comment interval


async def sse_stream(run_id: str) -> AsyncGenerator[str, None]:
    evpath = events_path(run_id)

    # Replay events already on disk; track last_pos by actual bytes read
    # (not st_size) so a line appended during replay is not silently skipped.
    last_pos = 0
    if evpath.exists():
        with open(evpath, "rb") as f:
            content = f.read()
            last_pos = f.tell()
        for line in content.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                yield f"data: {line}\n\n"

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
            with open(evpath, "rb") as f:
                f.seek(last_pos)
                chunk = f.read()

            # Only consume up to the last complete line (ends with \n),
            # so a half-written line is neither sent nor permanently skipped.
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                continue  # no complete line yet
            complete = chunk[: last_nl + 1]
            last_pos += last_nl + 1

            for line in complete.decode("utf-8").splitlines():
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
