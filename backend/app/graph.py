from __future__ import annotations

import sqlite3
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

from .config import PROJECT_ROOT, get_config
from .nodes.locate import run_locate
from .nodes.frames import run_frames
from .nodes.verify import run_verify
from .nodes.confirm import finish_confirm, start_confirm
from .nodes.photos import run_photos
from .nodes.plan import run_plan
from .nodes.search import run_search
from .nodes.extract import run_extract
from .nodes.pricing import run_pricing
from .nodes.report import run_report
from .runs import TERMINAL, append_event, node_result, read_events

_conn: sqlite3.Connection | None = None
_checkpointer: SqliteSaver | None = None


def _get_checkpointer() -> SqliteSaver:
    global _conn, _checkpointer
    if _checkpointer is None:
        cfg = get_config()
        db_path = PROJECT_ROOT / cfg.paths.runs_dir / "checkpoints.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _checkpointer = SqliteSaver(_conn)
    return _checkpointer


# Pipeline order after upload. A failed node stops the run there; resume_from() starts again at that node.
ORDER = ("locate", "frames", "verify", "confirm", "photos", "plan", "search", "extract", "pricing", "report")


class GraphState(TypedDict):
    run_id: str
    start_at: str
    locate_status: str
    frames_status: str
    verify_status: str
    confirm_status: str
    photos_status: str
    plan_status: str
    search_status: str
    extract_status: str
    pricing_status: str
    report_status: str


def _step(node: str, fn):
    """Run one node; its status is its own done/failed/skipped event (no event = did not finish = failed)."""
    def run(state: GraphState) -> GraphState:
        before = max((e.get("seq", 0) for e in read_events(state["run_id"])), default=0)
        fn(state["run_id"])
        ev = node_result(state["run_id"], node, before)
        return {**state, f"{node}_status": TERMINAL[ev["type"]] if ev else "failed"}
    return run


def _confirm_node(state: GraphState) -> GraphState:
    payload = start_confirm(state["run_id"])
    if payload is None:
        return {**state, "confirm_status": "skipped"}
    answer = interrupt(payload)  # pauses here; POST /confirm resumes with the user's answer
    finish_confirm(state["run_id"], payload, answer)
    return {**state, "confirm_status": "done"}


_RUNNERS = {"locate": run_locate, "frames": run_frames, "verify": run_verify,
            "photos": run_photos,  # skips itself when no photos were uploaded
            "plan": run_plan, "search": run_search, "extract": run_extract, "pricing": run_pricing,
            "report": run_report}


def _build_graph() -> object:
    g = StateGraph(GraphState)
    for node in ORDER:
        g.add_node(node, _confirm_node if node == "confirm" else _step(node, _RUNNERS[node]))
    g.set_conditional_entry_point(lambda s: s.get("start_at") or "locate", list(ORDER))
    for node, nxt in zip(ORDER, ORDER[1:] + (END,)):
        g.add_conditional_edges(node, lambda s, node=node, nxt=nxt: END if s.get(f"{node}_status") == "failed" else nxt,
                                list({nxt, END}))
    return g.compile(checkpointer=_get_checkpointer())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


import logging as _logging
_glog = _logging.getLogger(__name__)


def is_paused(run_id: str) -> bool:
    """True while the run's graph waits at the confirm interrupt (survives a restart via the checkpointer)."""
    state = get_graph().get_state({"configurable": {"thread_id": run_id}})
    return "confirm" in (state.next or ())


def _invoke(run_id: str, graph_input) -> None:
    config = {"configurable": {"thread_id": run_id}}
    try:
        get_graph().invoke(graph_input, config=config)
    except Exception as exc:
        _glog.exception("graph.invoke failed for %s: %s", run_id, exc)
        append_event(run_id, "pipeline", "run_done", {"status": "failed", "error": f"Pipeline error: {exc}"})
        return
    if is_paused(run_id):
        return
    values = get_graph().get_state(config).values
    failed = next((n for n in ORDER if values.get(f"{n}_status") == "failed"), None)
    if failed:  # stop here, nothing after it runs; POST /resume starts again at this node
        ev = node_result(run_id, failed)
        error = ((ev or {}).get("data") or {}).get("error") or f"{failed} did not finish"
        append_event(run_id, "pipeline", "run_done", {"status": "failed", "failed_at": failed, "error": error})
    else:
        append_event(run_id, "pipeline", "run_done", {"status": "partial"})


def _start_state(run_id: str, start_at: str) -> dict:
    return {"run_id": run_id, "start_at": start_at, **{f"{n}_status": "waiting" for n in ORDER}}


def run_graph(run_id: str) -> None:
    _invoke(run_id, _start_state(run_id, "locate"))


def resume_from(run_id: str, node: str) -> None:
    """Run the pipeline from `node` to the end (through the confirm pause when it is ahead)."""
    _invoke(run_id, _start_state(run_id, node))


def resume_graph(run_id: str, answer: dict) -> None:
    _invoke(run_id, Command(resume=answer))
