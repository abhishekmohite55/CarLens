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
from .nodes.confirm import finish_confirm, skip_photos, start_confirm
from .runs import append_event

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


class GraphState(TypedDict):
    run_id: str
    locate_status: str
    frames_status: str
    verify_status: str
    confirm_status: str


def _locate_node(state: GraphState) -> GraphState:
    run_locate(state["run_id"])
    return {**state, "locate_status": "done"}


def _frames_node(state: GraphState) -> GraphState:
    run_frames(state["run_id"])
    return {**state, "frames_status": "done"}


def _verify_node(state: GraphState) -> GraphState:
    run_verify(state["run_id"])
    return {**state, "verify_status": "done"}


def _confirm_node(state: GraphState) -> GraphState:
    payload = start_confirm(state["run_id"])
    if payload is None:
        return {**state, "confirm_status": "skipped"}
    answer = interrupt(payload)  # pauses here; POST /confirm resumes with the user's answer
    finish_confirm(state["run_id"], payload, answer)
    return {**state, "confirm_status": "done"}


def _photos_node(state: GraphState) -> GraphState:
    skip_photos(state["run_id"])
    return state


def _build_graph() -> object:
    g = StateGraph(GraphState)
    g.add_node("locate", _locate_node)
    g.add_node("frames", _frames_node)
    g.add_node("verify", _verify_node)
    g.set_entry_point("locate")
    g.add_edge("locate", "frames")
    g.add_edge("frames", "verify")
    g.add_node("confirm", _confirm_node)
    g.add_node("photos", _photos_node)
    g.add_edge("verify", "confirm")
    g.add_edge("confirm", "photos")
    g.add_edge("photos", END)
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
    try:
        get_graph().invoke(graph_input, config={"configurable": {"thread_id": run_id}})
    except Exception as exc:
        _glog.exception("graph.invoke failed for %s: %s", run_id, exc)
    if not is_paused(run_id):
        append_event(run_id, "pipeline", "run_done", {"status": "partial"})


def run_graph(run_id: str) -> None:
    _invoke(run_id, {"run_id": run_id, "locate_status": "waiting", "frames_status": "waiting",
                     "verify_status": "waiting", "confirm_status": "waiting"})


def resume_graph(run_id: str, answer: dict) -> None:
    _invoke(run_id, Command(resume=answer))
