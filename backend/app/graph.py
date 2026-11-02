from __future__ import annotations

import sqlite3
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import PROJECT_ROOT, get_config
from .nodes.locate import run_locate
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


def _locate_node(state: GraphState) -> GraphState:
    run_locate(state["run_id"])
    return {**state, "locate_status": "done"}


def _build_graph() -> object:
    g = StateGraph(GraphState)
    g.add_node("locate", _locate_node)
    g.set_entry_point("locate")
    g.add_edge("locate", END)
    return g.compile(checkpointer=_get_checkpointer())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_graph(run_id: str) -> None:
    graph = get_graph()
    config = {"configurable": {"thread_id": run_id}}
    try:
        graph.invoke({"run_id": run_id, "locate_status": "waiting"}, config=config)
    except Exception:
        pass  # node_failed already written by the node; graph must not crash the thread
    finally:
        append_event(run_id, "pipeline", "run_done", {"status": "partial"})
