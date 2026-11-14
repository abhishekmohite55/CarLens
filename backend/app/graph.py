from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command, interrupt

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.engine import make_url

from .config import get_config, pinned_run
from .db import database_url
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

_checkpointer: PostgresSaver | None = None


def _get_checkpointer() -> PostgresSaver:
    """Confirm pause in Postgres (stage 2.5b; was runs/checkpoints.sqlite). setup() creates LangGraph's own tables once."""
    global _checkpointer
    if _checkpointer is None:
        url = database_url()
        if not url:
            raise RuntimeError("DATABASE_URL is not set in .env")
        u = make_url(url)  # parsed like the rest of the backend (SQLAlchemy), so the password is read the same way
        # connect_timeout: a host that does not answer (e.g. "localhost" → IPv6 ::1 on Windows) fails in 10 s, not minutes
        conninfo = make_conninfo(host=u.host, port=u.port, dbname=u.database, user=u.username, password=u.password,
                                 connect_timeout=10)
        pool = ConnectionPool(conninfo=conninfo, max_size=10, open=True,
                              kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        saver = PostgresSaver(pool)
        saver.setup()  # kept only after setup worked, so a failed setup is retried (and its error shown) next time
        _checkpointer = saver
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


def _past_stop(node: str) -> bool:
    """True when config.yaml dev.stop_after names a node at or before this one (read on every run)."""
    stop = get_config().dev.stop_after
    return stop in ORDER and ORDER.index(node) > ORDER.index(stop)


def _after(state: GraphState, node: str, nxt: str) -> str:
    """Next node, or END when this node failed or the next one is past dev.stop_after."""
    if state.get(f"{node}_status") == "failed" or nxt == END:
        return END
    with pinned_run(state.get("run_id")):  # the run's own config version (step 6.3)
        return END if _past_stop(nxt) else nxt


def _entry(state: GraphState) -> str:
    """Start node; END when it is past dev.stop_after (e.g. confirm by hand must not start photos … report)."""
    start = state.get("start_at") or "locate"
    with pinned_run(state.get("run_id")):
        return END if _past_stop(start) else start


def _build_graph() -> object:
    g = StateGraph(GraphState)
    for node in ORDER:
        g.add_node(node, _confirm_node if node == "confirm" else _step(node, _RUNNERS[node]))
    g.set_conditional_entry_point(_entry, list(ORDER) + [END])
    for node, nxt in zip(ORDER, ORDER[1:] + (END,)):
        g.add_conditional_edges(node, lambda s, node=node, nxt=nxt: _after(s, node, nxt), list({nxt, END}))
    return g.compile(checkpointer=_get_checkpointer())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


import logging as _logging
_glog = _logging.getLogger(__name__)


def forget_run(run_id: str) -> None:
    """Delete the run's paused state (LangGraph checkpoint rows); used when the admin deletes a run."""
    _get_checkpointer().delete_thread(run_id)


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
    else:  # complete only when the report is done; partial = ended early (dev.stop_after)
        status = "complete" if values.get("report_status") == "done" else "partial"
        append_event(run_id, "pipeline", "run_done", {"status": status})


def _start_state(run_id: str, start_at: str) -> dict:
    return {"run_id": run_id, "start_at": start_at, **{f"{n}_status": "waiting" for n in ORDER}}


def run_graph(run_id: str) -> None:
    _invoke(run_id, _start_state(run_id, "locate"))


def resume_from(run_id: str, node: str) -> None:
    """Run the pipeline from `node` to the end (through the confirm pause when it is ahead)."""
    _invoke(run_id, _start_state(run_id, node))


def resume_graph(run_id: str, answer: dict) -> None:
    _invoke(run_id, Command(resume=answer))
