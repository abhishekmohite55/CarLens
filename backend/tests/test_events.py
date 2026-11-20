"""Tests for SSE stream gap fix in events.py."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

pytest_plugins = ('anyio',)


@pytest.mark.anyio
async def test_replay_last_pos_not_skipped_by_race():
    """After replay, an event appended before the first follow-loop poll must be delivered.

    Old bug: last_pos = st_size captured AFTER file written → new event skipped.
    Fix:     last_pos = f.tell() captured DURING replay read → new event not skipped.
    """
    import app.events as ev_mod

    # Patch events_path inside events.py (imported by name via `from .runs import events_path`
    # — patching runs_mod.events_path does NOT affect the already-bound name in events.py).
    original_ep = ev_mod.events_path
    original_poll = ev_mod._POLL_INTERVAL
    ev_mod._POLL_INTERVAL = 0.05  # fast poll for test

    with tempfile.TemporaryDirectory() as tmpdir:
        evfile = Path(tmpdir) / "events.jsonl"
        run_id = "test_gap_run_x"

        evfile.write_text(
            '{"seq":1,"type":"node_done"}\n'
            '{"seq":2,"type":"node_done"}\n'
            '{"seq":3,"type":"node_done"}\n',
            encoding="utf-8",
        )

        ev_mod.events_path = lambda rid: evfile if rid == run_id else original_ep(rid)

        gen = None
        try:
            gen = ev_mod.sse_stream(run_id)

            # Drain all 3 replay events by calling __anext__ directly.
            # (async for + break calls aclose() which closes the generator.)
            ev1 = await gen.__anext__()
            ev2 = await gen.__anext__()
            ev3 = await gen.__anext__()
            assert '"seq":1' in ev1, f"expected seq1 in {ev1!r}"
            assert '"seq":2' in ev2, f"expected seq2 in {ev2!r}"
            assert '"seq":3' in ev3, f"expected seq3 in {ev3!r}"

            # Append 4th event — simulates race window after replay.
            # Fix ensures last_pos was captured from f.tell() BEFORE any yields,
            # so the follow loop sees the new data.
            with open(evfile, "a", encoding="utf-8") as f:
                f.write('{"seq":4,"type":"node_done"}\n')

            # Must arrive within 1 s (poll=50 ms, 20× margin)
            ev4 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            assert '"seq":4' in ev4, f"Expected seq 4, got: {ev4!r}"

        finally:
            ev_mod.events_path = original_ep
            ev_mod._POLL_INTERVAL = original_poll
            if gen is not None:
                await gen.aclose()


def test_lines_after_skips_old_events_and_sees_the_end():  # hardening A7
    from app.events import lines_after, sse_message
    lines = ['{"seq":1,"type":"node_started"}', "", '{"seq":2,"type":"node_done"}',
             '{"seq":3,"node":"pipeline","type":"run_done"}']
    fresh, ended = lines_after(lines, after=1)
    assert [s for s, _ in fresh] == [2, 3] and ended
    fresh, ended = lines_after(lines[:3], after=0)
    assert [s for s, _ in fresh] == [1, 2] and not ended
    # a resumed run: run_done in the middle is not the end
    fresh, ended = lines_after(lines + ['{"seq":4,"type":"node_started"}'], after=3)
    assert [s for s, _ in fresh] == [4] and not ended
    assert sse_message(7, "{}") == "id: 7\ndata: {}\n\n"


@pytest.mark.anyio
async def test_stream_ends_after_run_done_and_resumes_after_seq(tmp_path):  # hardening A7
    import app.events as ev_mod
    evfile = tmp_path / "events.jsonl"
    evfile.write_text('{"seq":1,"type":"node_done"}\n{"seq":2,"node":"pipeline","type":"run_done"}\n',
                      encoding="utf-8")
    original_ep = ev_mod.events_path
    ev_mod.events_path = lambda rid: evfile
    try:
        sent = [m async for m in ev_mod.sse_stream("r_x", after=1)]  # ends by itself: no hang
        assert len(sent) == 2 and '"seq":2' in sent[0] and sent[1].startswith("retry:")
        assert ev_mod.open_streams() == 0
    finally:
        ev_mod.events_path = original_ep


def test_resume_point_takes_the_larger_of_after_and_last_event_id():  # hardening A7
    from app.main import resume_point
    assert resume_point(0, None) == 0
    assert resume_point(5, "3") == 5
    assert resume_point(2, "9") == 9
    assert resume_point(-4, "not a number") == 0
