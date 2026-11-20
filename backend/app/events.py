"""Live run events over SSE (stage 1; hardening A7, docs/platform/10-hardening-findings.md §8).

Every event goes out with `id: <seq>`. A (re)connect sends only events after `after` (the page's last seq, or the
browser's Last-Event-ID), never the whole history again. The stream ends once the run's last event is run_done:
a finished run's tab stops asking. Resume opens a new stream from the last seq it has.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import AsyncGenerator

from starlette.concurrency import run_in_threadpool

from .runs import events_path

_POLL_INTERVAL = 0.5   # seconds between file checks
_KEEPALIVE_SEC = 15    # SSE keep-alive comment interval
_RETRY_AFTER_END_MS = 60_000  # a browser that reconnects by itself after the end waits this long

_open_streams = 0
_open_lock = threading.Lock()


def open_streams() -> int:
    with _open_lock:
        return _open_streams


def _count_stream(change: int) -> None:
    global _open_streams
    with _open_lock:
        _open_streams = max(0, _open_streams + change)


def parse_event_line(line: str) -> tuple[int, bool]:
    """(seq, is run_done) of one events.jsonl line; seq 0 when unreadable (always sent, never ends the stream)."""
    try:
        event = json.loads(line)
        return int(event.get("seq") or 0), event.get("type") == "run_done"
    except (ValueError, TypeError, AttributeError):
        return 0, False


def lines_after(lines: list[str], after: int) -> tuple[list[tuple[int, str]], bool]:
    """The non-empty lines with seq > after, as (seq, line), and whether the last event of all is run_done."""
    out: list[tuple[int, str]] = []
    ended = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        seq, is_done = parse_event_line(line)
        ended = is_done
        if seq == 0 or seq > after:
            out.append((seq, line))
    return out, ended


def read_from(path: Path, pos: int) -> tuple[bytes, int]:
    """The file's bytes from pos on, and the position after them (S8: called in a worker thread)."""
    with open(path, "rb") as f:
        f.seek(pos)
        data = f.read()
        return data, f.tell()


def sse_message(seq: int, line: str) -> str:
    return f"id: {seq}\ndata: {line}\n\n" if seq else f"data: {line}\n\n"


async def sse_stream(run_id: str, after: int = 0) -> AsyncGenerator[str, None]:
    _count_stream(+1)
    try:
        evpath = events_path(run_id)

        # Replay events already on disk; track last_pos by actual bytes read
        # (not st_size) so a line appended during replay is not silently skipped.
        last_pos = 0
        ended = False
        if evpath.exists():
            content, last_pos = await run_in_threadpool(read_from, evpath, 0)
            fresh, ended = lines_after(content.decode("utf-8").splitlines(), after)
            for seq, line in fresh:
                yield sse_message(seq, line)
        if ended:
            yield f"retry: {_RETRY_AFTER_END_MS}\n\n"
            return

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
                chunk, _ = await run_in_threadpool(read_from, evpath, last_pos)

                # Only consume up to the last complete line (ends with \n),
                # so a half-written line is neither sent nor permanently skipped.
                last_nl = chunk.rfind(b"\n")
                if last_nl == -1:
                    continue  # no complete line yet
                complete = chunk[: last_nl + 1]
                last_pos += last_nl + 1

                fresh, ended = lines_after(complete.decode("utf-8").splitlines(), after)
                for seq, line in fresh:
                    yield sse_message(seq, line)
                if ended:
                    yield f"retry: {_RETRY_AFTER_END_MS}\n\n"
                    return
    finally:
        _count_stream(-1)
