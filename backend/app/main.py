from __future__ import annotations

import json
import shutil
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from typing import Literal, Optional

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from .auth import NO_STORE, AuthError, SignedIn, require_admin, require_approved, signed_in_user
from .admin_routes import router as admin_router
from .auth_routes import router as auth_router
from .config import get_config
from .events import open_streams, sse_stream
from .graph import is_paused, resume_from, resume_graph, run_graph
from .nodes.locate import run_locate
from .nodes.locate import try_claim as locate_try_claim
from .nodes.confirm import (PAYLOAD_FILE, RECORD_FILE, finish_confirm, load_payload, load_record, load_verify_answer,
                            rto_rows, start_confirm)
from .nodes.photos import save_photo
from .photos import SLOTS
from .nodes.frames import load_locate_items, run_frames
from .nodes.frames import try_claim as frames_try_claim
from .nodes.verify import run_verify
from .nodes.plan import run_plan
from .nodes.plan import try_claim as plan_try_claim
from .nodes.search import run_search
from .nodes.search import try_claim as search_try_claim
from .nodes.extract import run_extract
from .nodes.extract import try_claim as extract_try_claim
from .nodes.pricing import run_pricing
from .nodes.pricing import try_claim as pricing_try_claim
from .nodes.report import run_report
from .nodes.report import try_claim as report_try_claim
from .nodes.verify import try_claim as verify_try_claim
from .llm.tracing import _get_client as _warmup_tracing
from .nodes.upload import (DuplicateUpload, body_too_large, claim_upload_slot, clean_old_pending, drop_pending,
                           process_upload, release_upload_slot, start_pending)
from .db import get_engine
from .results import FILES as RESULT_FILES, delete_results, load_result
from .run_index import (FLAGGED_REFUSALS, RunRefused, admission_refusal, busy, busy_refusal, busy_runs, is_run_id,
                        log_upload_event, resume_allowed, close_open_rows, interrupted_nodes, latest_node_result, other_active_run, run_owner,
                        user_runs, run_status, market_off_refusal)
from .market import US_STATES, market_is_on, resolve_market, state_guess
from .vin.lookup import VinError, lookup_vin
from .runs import append_event, events_path, failed_at, failure_count, run_dir
from .settings_store import SettingsError, repin_run, run_market
from .storage import fetch_run, push_run
from .health import check as health_check
from .maintenance import refuse_late_confirm, refuse_new_work, state as maintenance_state

# run_ids that have started or are starting the graph
_started: set[str] = set()
_start_lock = threading.Lock()

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Runs once when the server starts (before the first request), then the server runs."""
    _warmup_tracing()
    _mark_interrupted()
    clean_old_pending()
    yield


# /docs and /openapi.json are served below, admin only (platform step 5).
app = FastAPI(title="CarLens backend", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)
app.include_router(admin_router)

# Who may call what: 05-login.md §6. Upload and run routes stay admin-only until stage 5.3 (tokens, own runs).
_ADMIN = [Depends(require_admin)]
_APPROVED = [Depends(require_approved)]


def run_access(run_id: str, user: SignedIn = Depends(require_approved)) -> SignedIn:
    """The admin opens every run; a user only their own. Someone else's run answers 404, so ids cannot be probed."""
    if user.role != "admin":
        exists, owner = run_owner(run_id)
        if not exists or owner != user.id:
            raise AuthError(404, "not_found", "Run not found.")
    return user


def visitor_market(request: Request, user: SignedIn, admin_choice: str | None) -> str:
    """Stage M0 (07-us-market.md §3): the admin's pin on the user, the admin's own switch (admin only), the
    CloudFront-Viewer-Country header through markets.country_map, markets.default."""
    markets = get_config().markets
    return resolve_market(user_market=user.market, is_admin=user.role == "admin", admin_choice=admin_choice,
                          country=request.headers.get("CloudFront-Viewer-Country"),
                          country_map=markets.country_map, default=markets.default)


def refuse_market_off(market: str) -> None:
    """Stage M0: dev.markets_on has this market off: no run starts (no token, no AI or Tavily call)."""
    if not market_is_on(get_config().dev.markets_on, market):
        raise market_off_refusal(market)


def refuse_run_market_off(run_id: str) -> None:
    """Route dependency (resume, dev re-runs): the run's own market must be on."""
    refuse_market_off(run_market(run_id))


_RUN = [Depends(run_access)]
_NEW_WORK = [Depends(refuse_new_work)]  # step 9: refused while maintenance is on (deploy)
_ADMIN_WORK = _ADMIN + _NEW_WORK + [Depends(refuse_run_market_off)]  # every _ADMIN_WORK route has {run_id}


@app.exception_handler(SettingsError)
def _settings_error(request: Request, exc: SettingsError):
    """A config or prompt save that was refused: every problem with its field."""
    return JSONResponse(status_code=422, content={
        "error": {"code": "invalid", "message": str(exc), "problems": exc.problems}})


@app.exception_handler(AuthError)
@app.exception_handler(RunRefused)
def _auth_error(request: Request, exc: AuthError | RunRefused):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


def _mark_interrupted() -> None:
    """H1 (stage 2.5b): a node cut off by a server stop never sent done/failed; mark it failed so Resume is offered."""
    if get_engine() is None:
        return
    error = "Server stopped while this node was running"
    for run_id, node in interrupted_nodes():
        if run_dir(run_id).exists():
            append_event(run_id, node, "node_failed", {"error": error})
            append_event(run_id, "pipeline", "run_done", {"status": "failed", "failed_at": node, "error": error})
        close_open_rows(run_id, node, error, datetime.now(timezone.utc))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_INSPECTOR = Path(__file__).parent.parent / "inspector" / "index.html"

# Node list — ids and labels from 02-design.md §3.2
_NODES = [
    {"id": "upload",  "label": "Upload & check"},
    {"id": "locate",  "label": "Locate (Gemini)"},
    {"id": "frames",  "label": "Extract frames"},
    {"id": "verify",  "label": "Verify (AI)"},
    {"id": "confirm", "label": "You confirm"},
    {"id": "photos",  "label": "Extra photos (Gemini)"},
    {"id": "plan",    "label": "Plan searches (LLM)"},
    {"id": "search",  "label": "Search web (Tavily)"},
    {"id": "extract", "label": "Read prices (LLM)"},
    {"id": "pricing", "label": "Price (Python)"},
    {"id": "report",  "label": "Report"},
]


def _local_run(run_id: str, with_video: bool = False) -> Path:
    """The run folder on this server; brought back from S3 first when it was pruned (step 8.1).
    with_video: also the video (resume and admin re-runs may start at locate or frames).
    Any id that is not a run id answers 404 before files or S3 are touched (hardening S14)."""
    if not is_run_id(run_id):
        raise HTTPException(404, detail="Run not found.")
    fetch_run(run_id, with_video=with_video)
    return run_dir(run_id)


@app.get("/api/health")
def api_health():
    """Step 9.3: public, no details: {"status": "ok" | "degraded", "version"}. The deploy waits for "ok"."""
    return health_check()


@app.get("/api/config")
def api_config(request: Request, market: str | None = None, user: SignedIn = Depends(require_approved)):
    """market (query): the admin's own switch (inspector); ignored for everyone else (stage M0)."""
    cfg = get_config()
    return {
        "market": visitor_market(request, user, market),  # stage M0
        "markets_on": cfg.dev.markets_on,
        "us": {  # stage U1: US first screen (state chips, type-ahead, guess from CloudFront's region header)
            "top_states": cfg.markets.us.top_states,
            "states": [{"code": code, "name": name} for code, name in US_STATES.items()],
            "state_guess": state_guess(request.headers.get("CloudFront-Viewer-Country-Region")),
        },
        "upload": {
            "allowed_types": cfg.upload.allowed_types,
            "max_size_mb": cfg.upload.max_size_mb,
            "max_duration_sec": cfg.upload.max_duration_sec,
        },
        "nodes": _NODES,
        "maintenance": maintenance_state()["on"],  # step 9: the app shows "being updated" and keeps uploads closed
        "busy": _server_busy(cfg.access.max_active_runs),  # hardening A2: Home says "busy" before an upload starts
    }


class VinBody(BaseModel):
    vin: str = Field(max_length=64)


@app.post("/api/vin/lookup")
def api_vin_lookup(body: VinBody, user: SignedIn = Depends(require_approved)):
    """Stage U1 (07-us-market.md §4): the car for a VIN, or a plain message. US market off → refused (closed is
    closed, owner 26 Nov). 422 vin_invalid / vin_not_found, 429 too_many, 503 vin_unavailable."""
    refuse_market_off("us")
    try:
        return lookup_vin(body.vin, user.id, get_config().vin, is_admin=user.role == "admin")
    except VinError as exc:
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message},
                                                             "answer": exc.answer})


def _server_busy(max_active_runs: int) -> bool:
    try:
        return busy(busy_runs(), max_active_runs)
    except Exception:  # noqa: BLE001  no database: the upload itself will say what is wrong
        return False


@app.post("/api/runs", dependencies=_NEW_WORK)
async def api_create_run(request: Request, background: BackgroundTasks, market: str | None = None,
                         user: SignedIn = Depends(require_approved)):
    """Upload → new run. Users: 1 token, one run at a time, same video again asks first (05-login.md §7.2, §7.3).
    Hardening A2: no `video: UploadFile` parameter (FastAPI would read the whole body before any check). Admission
    first (size, tokens, run in progress, server busy, uploads at once), then the form is read.
    Stage M0: the run's market is resolved first (market query = the admin's switch, ignored for users); a market
    that is off is refused before anything is read or spent."""
    cfg = get_config()
    is_admin = user.role == "admin"
    run_market_now = visitor_market(request, user, market)
    refuse_market_off(run_market_now)
    if body_too_large(request.headers.get("content-length"), cfg.upload.max_size_mb):
        return JSONResponse(status_code=413, content={"error": {"code": "too_large", "message":
                            f"This file exceeds {cfg.upload.max_size_mb} MB. The limit is {cfg.upload.max_size_mb} MB."}})
    if not is_admin:
        refused = await run_in_threadpool(admission_refusal, user.id, cfg.access.max_active_runs)
        if refused:
            await _log_refusal(user.id, refused)
            raise refused
        if not claim_upload_slot(cfg.upload.max_parallel):
            raise busy_refusal()
    form = None
    try:
        form = await request.form(max_files=1, max_fields=1)
        video = form.get("video")
        if not isinstance(video, StarletteUploadFile):
            return JSONResponse(status_code=400, content={"error": {"code": "no_video", "message": "No video was sent."}})
        out = await process_upload(video, user.id, is_admin=is_admin, market=run_market_now)
        background.add_task(push_run, out["run_id"])  # the video to S3 (step 8.1)
        return out
    except DuplicateUpload as dup:
        return JSONResponse(status_code=409, content={
            "error": {"code": "same_video", "message": "You uploaded this video before. Open the old run, or start a fresh run (1 token)."},
            "duplicate_of": dup.duplicate_of, "pending_id": dup.pending_id})
    except RunRefused as refused:  # the atomic check in create_run_row (a race the admission did not see)
        if not is_admin:
            await _log_refusal(user.id, refused)
        raise
    finally:
        if form is not None:
            await form.close()
        if not is_admin:
            release_upload_slot()


async def _log_refusal(user_id: int, refused: RunRefused) -> None:
    """Hardening A2: refusals a normal user never meets (Home blocks them) are counted for the dashboard."""
    if refused.code in FLAGGED_REFUSALS:
        await run_in_threadpool(log_upload_event, user_id, "upload_refused", {"code": refused.code})


@app.get("/api/runs")
def api_list_runs(user: SignedIn = Depends(require_approved)):
    """The signed-in user's runs, newest first (the admin sees every run)."""
    return {"runs": user_runs(None if user.role == "admin" else user.id)}


@app.post("/api/uploads/{pending_id}/start", dependencies=_NEW_WORK)
def api_start_pending(pending_id: str, background: BackgroundTasks, user: SignedIn = Depends(require_approved)):
    """Same video again → "fresh run": the kept upload becomes a new run (1 token)."""
    out = start_pending(pending_id, user.id)
    background.add_task(push_run, out["run_id"])  # the video to S3 (step 8.1)
    return out


@app.delete("/api/uploads/{pending_id}")
def api_drop_pending(pending_id: str, user: SignedIn = Depends(require_approved)):
    """Same video again → "open old run": the kept upload is deleted, no token spent."""
    drop_pending(pending_id, user.id)
    return {"ok": True}


@app.get("/api/runs/{run_id}", dependencies=_RUN)
def api_get_run(run_id: str):
    rd = _local_run(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    meta = load_result(run_id, "meta.json") or {}

    node_status: dict[str, str] = {n["id"]: "waiting" for n in _NODES}
    ev_path = rd / "events.jsonl"
    if ev_path.exists():
        with open(ev_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                node = ev.get("node", "")
                etype = ev.get("type", "")
                if node not in node_status:
                    continue
                if etype == "node_started" and node_status[node] == "waiting":
                    node_status[node] = "running"
                elif etype == "node_done":
                    node_status[node] = "done"
                elif etype == "node_failed":
                    node_status[node] = "failed"
                elif etype == "node_skipped":
                    node_status[node] = "skipped"

    return {"run_id": run_id, "meta": meta, "nodes": node_status}


def _has_locate_event(run_id: str) -> bool:
    """True once the run got past upload: a locate event, or a run_done (a run ended before it started must not start)."""
    ep = events_path(run_id)
    if not ep.exists():
        return False
    with open(ep, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
                if ev.get("node") == "locate" or ev.get("type") == "run_done":
                    return True
            except json.JSONDecodeError:
                pass
    return False


@app.post("/api/runs/{run_id}/end", dependencies=_RUN)
def api_end_run(run_id: str):
    """A video uploaded but never started (tab closed): end it so the user can start a fresh run (owner, 12-14 Nov).
    The run ends partial; its token is not given back (resume is free instead)."""
    with _start_lock:
        if run_status(run_id) != "uploaded" or run_id in _started:
            return JSONResponse(status_code=409, content={
                "error": {"code": "already_started", "message": "This run has already started."}})
        append_event(run_id, "pipeline", "run_done", {"status": "partial", "error": "Ended before it started"})
    return {"ended": True}


def resume_point(after: int, last_event_id: str | None) -> int:
    """Hardening A7: the last seq the page already has (?after= or the browser's Last-Event-ID), never negative."""
    try:
        header = int(last_event_id) if last_event_id else 0
    except ValueError:
        header = 0
    return max(0, after, header)


@app.get("/api/runs/{run_id}/events", dependencies=_RUN)
async def api_run_events(run_id: str, request: Request, after: int = 0):
    rd = await run_in_threadpool(_local_run, run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if open_streams() >= get_config().access.max_event_streams:  # hardening A7
        raise busy_refusal()

    with _start_lock:
        # a run uploaded just before maintenance waits; it starts when the page is opened after the update
        if (run_id not in _started and not _has_locate_event(run_id) and not maintenance_state()["on"]
                and market_is_on(get_config().dev.markets_on, run_market(run_id))):  # stage M0: market off waits
            _started.add(run_id)
            t = threading.Thread(target=run_graph, args=(run_id,), daemon=True)
            t.start()

    return StreamingResponse(
        sse_stream(run_id, resume_point(after, request.headers.get("last-event-id"))),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _single_step(run_id: str, node: str, step) -> None:
    """Dev re-run of one step (inspector buttons). A pipeline run ends with run_done; a single step did not, so the
    run stayed "running" (owner check, 12 Nov). Now: run_done partial (stopped after this step) or failed at it.
    Skipped while the run's graph waits at confirm (its status stays awaiting_confirm)."""
    try:
        repin_run(run_id)  # a new attempt uses the config and prompts active now (step 6.3)
        step(run_id, claimed=True)
    finally:
        if not is_paused(run_id):
            status, error = latest_node_result(run_id, node)
            if status == "failed":
                append_event(run_id, "pipeline", "run_done", {"status": "failed", "failed_at": node, "error": error})
            else:
                append_event(run_id, "pipeline", "run_done", {"status": "partial", "stopped_after": node})
        push_run(run_id)  # S3 copy (step 8.1)


# What a node clears before it runs again (resume). Locate keeps video_small.mp4, photos keep the uploaded jpgs.
_NODE_FILES = {"locate": ["01_locate/request.json", "01_locate/response.json"],
               "confirm": [PAYLOAD_FILE, RECORD_FILE],
               "verify": ["03_verify"],
               "photos": ["05_photos/request.json", "05_photos/response.json", "05_photos/applied.json"],
               "plan": ["06_plan"], "search": ["07_search"], "extract": ["08_extract"],
               "pricing": ["09_report/price.json"], "report": ["09_report/report.json"]}
_resuming: set[str] = set()
_resume_lock = threading.Lock()


def _clear_node(rd: Path, node: str) -> None:
    delete_results(rd.name, node)  # rows saved in the database (stage 2.x); folder = run id
    for rel in _NODE_FILES.get(node, []):
        p = rd / rel
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)


@app.post("/api/runs/{run_id}/locate", status_code=202, dependencies=_ADMIN_WORK)
def api_run_locate(run_id: str):
    """Dev (used by /inspector): re-run only locate; reuses 01_locate/video_small.mp4 when the shrink already finished."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not locate_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Locate is already running for this run."}
        })
    _clear_node(rd, "locate")
    threading.Thread(target=_single_step, args=(run_id, "locate", run_locate), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/resume", status_code=202, dependencies=_NEW_WORK + [Depends(refuse_run_market_off)])
def api_resume(run_id: str, user: SignedIn = Depends(run_access)):
    """Start the pipeline again at the node the run stopped at, then carry on to the end. Free (no token)."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if user.role != "admin" and other_active_run(user.id, run_id):
        raise RunRefused(409, "run_in_progress", "You already have a run in progress. Wait until it is finished.")
    if run_id in _resuming or is_paused(run_id):  # before the limits: a run already going is not "busy" (fix 20 Nov)
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "This run is already running or waiting for confirm."}
        })
    node = failed_at(run_id)
    if node is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_failed", "message": "Nothing to resume: the last run did not stop on a failure."}
        })
    if user.role != "admin":  # hardening A7: Resume stays free, but not endless, and waits when the server is full
        access = get_config().access
        if not resume_allowed(failure_count(run_id), access.free_resumes_per_run):
            raise RunRefused(409, "resume_limit", "This run stopped too many times. Start a fresh run.")
        if busy(busy_runs(), access.max_active_runs):
            raise busy_refusal()
    with _resume_lock:
        if run_id in _resuming or is_paused(run_id):
            return JSONResponse(status_code=409, content={
                "error": {"code": "already_running", "message": "This run is already running or waiting for confirm."}
            })
        _resuming.add(run_id)
    repin_run(run_id)  # resume uses the config and prompts active now (step 6.3)
    _clear_node(rd, node)
    # Written before the answer (fix 20 Nov): the page reconnects at once, and a stream whose last event is still
    # the old run_done would end before the resumed run writes anything.
    append_event(run_id, "pipeline", "run_resumed", {"from": node})

    def _go():
        try:
            resume_from(run_id, node)
        finally:
            _resuming.discard(run_id)
    threading.Thread(target=_go, daemon=True).start()
    return {"resuming_from": node}


@app.post("/api/runs/{run_id}/frames", status_code=202, dependencies=_ADMIN_WORK)
def api_run_frames(run_id: str):
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    if load_locate_items(run_id) is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_locate_result", "message": "Locate has no valid result for this run."}
        })

    if not frames_try_claim(run_id):  # also covers a frames run started by the graph after an upload
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Frames extraction is already running for this run."}
        })

    threading.Thread(target=_single_step, args=(run_id, "frames", run_frames), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/verify", status_code=202, dependencies=_ADMIN_WORK)
def api_run_verify(run_id: str):
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    if load_result(run_id, "02_frames/manifest.json") is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_frames_result", "message": "Frames have no manifest for this run."}
        })

    if not verify_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Verify is already running for this run."}
        })

    _clear_node(rd, "verify")  # old 03_verify folder (pre-step-2 runs) and its database rows

    threading.Thread(target=_single_step, args=(run_id, "verify", run_verify), daemon=True).start()
    return {"started": True}


class CarAnswer(BaseModel):
    make: str = Field(min_length=1)    # required: plan needs make and model to build queries
    model: str = Field(min_length=1)
    variant: Optional[str] = None
    year: Optional[int] = Field(None, ge=1950, le=2100)
    fuel: Optional[str] = None


class ConfirmAnswer(BaseModel):
    car: CarAnswer
    plate: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    odometer_km: Optional[int] = Field(None, ge=0, le=2_000_000)
    skipped: list[Literal["tyre_photo", "odometer"]] = []


_confirming: set[str] = set()
_confirm_lock = threading.Lock()
_photo_work: dict[str, int] = {}  # hardening U2: photo uploads/removals in progress, per run (under _confirm_lock)


def _claim_photo(run_id: str) -> bool:
    """Count a photo change as in progress. False once confirm has started: photos can no longer change."""
    with _confirm_lock:
        if run_id in _confirming:
            return False
        _photo_work[run_id] = _photo_work.get(run_id, 0) + 1
        return True


def _release_photo(run_id: str) -> None:
    with _confirm_lock:
        left = _photo_work.get(run_id, 1) - 1
        if left > 0:
            _photo_work[run_id] = left
        else:
            _photo_work.pop(run_id, None)


_PHOTO_CLOSED = {"error": {"code": "not_waiting", "message": "Photos can only be changed while confirm is waiting."}}


@app.post("/api/runs/{run_id}/confirm/start", dependencies=_ADMIN_WORK)
def api_confirm_start(run_id: str):
    """Dev (used by /inspector): show the confirm step on a run whose graph already ended after verify.
    Admin only (hardening A1): it clears confirm and photos, and the confirm that follows reruns paid steps."""
    rd = _local_run(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not load_verify_answer(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_verify_result", "message": "Verify has no answer for this run."}
        })
    if is_paused(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_waiting", "message": "This run is already waiting for confirm."}
        })
    _clear_node(rd, "confirm")  # payload + record rows (and pre-step-2 files)
    _clear_node(rd, "photos")  # a fresh confirm starts without old photo answers and photos
    if (rd / "05_photos").exists():
        shutil.rmtree(rd / "05_photos")
    start_confirm(run_id)
    return {"started": True}


@app.post("/api/runs/{run_id}/confirm", dependencies=_RUN + [Depends(refuse_late_confirm)])
def api_confirm(run_id: str, answer: ConfirmAnswer, user: SignedIn = Depends(run_access)):
    rd = _local_run(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    with _confirm_lock:
        payload = load_payload(run_id)
        if payload is None:
            return JSONResponse(status_code=409, content={
                "error": {"code": "not_waiting", "message": "This run is not waiting for confirm."}
            })
        if load_record(run_id) is not None or run_id in _confirming:
            return JSONResponse(status_code=409, content={
                "error": {"code": "already_confirmed", "message": "This run is already confirmed."}
            })
        if _photo_work.get(run_id):  # hardening U2: confirm never overtakes a photo still uploading
            return JSONResponse(status_code=409, content={
                "error": {"code": "photo_uploading", "message": "A photo is still uploading. Wait for it to finish, then confirm."}
            })
        paused = is_paused(run_id)
        if not paused and user.role != "admin":  # hardening A1: only the admin's dev path confirms a run not paused
            return JSONResponse(status_code=409, content={
                "error": {"code": "not_waiting", "message": "This run is not waiting for confirm."}
            })
        _confirming.add(run_id)
    data = answer.model_dump()
    try:
        if paused:
            threading.Thread(target=resume_graph, args=(run_id, data), daemon=True).start()
        else:  # dev path: run started with "Start confirm", no graph waiting
            finish_confirm(run_id, payload, data)
            # rest of the pipeline through the graph, so it stops at the first failed node like a normal run
            threading.Thread(target=resume_from, args=(run_id, "photos"), daemon=True).start()
    finally:
        _confirming.discard(run_id)  # 04_confirm.json now guards repeats
    return {"confirmed": True}


def _photo_guard(run_id: str, slot: str):
    """Photos can change only while confirm waits; the odometer slot only when the video read no km."""
    rd = _local_run(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if slot not in SLOTS:
        raise HTTPException(404, detail=f"Unknown photo slot '{slot}'.")
    payload = load_payload(run_id)
    if payload is None or load_record(run_id) is not None:
        return rd, JSONResponse(status_code=409, content={
            **_PHOTO_CLOSED
        })
    if slot == "odometer" and payload.get("odometer_found"):
        return rd, JSONResponse(status_code=409, content={
            "error": {"code": "odometer_read", "message": "The video already read the odometer."}
        })
    return rd, None


@app.post("/api/runs/{run_id}/photos/{slot}", dependencies=_RUN)
async def api_upload_photo(run_id: str, slot: str, photo: UploadFile = File(...)):
    """Stage 6: one extra photo per slot (front_left, front_right, rear_left, rear_right, odometer); replaces the old one."""
    if not _claim_photo(run_id):
        return JSONResponse(status_code=409, content=_PHOTO_CLOSED)
    try:
        rd, err = await run_in_threadpool(_photo_guard, run_id, slot)  # S8: database and files off the event loop
        if err:
            return err
        data = await photo.read(get_config().photos.max_size_mb * 1024 * 1024 + 1)
        problem = await run_in_threadpool(save_photo, rd / "05_photos", slot, photo.filename or "", data)  # hardening A4
        if problem:
            return JSONResponse(status_code=422, content={"error": {"code": "bad_photo", "message": problem}})
        return {"saved": f"05_photos/{slot}.jpg"}
    finally:
        _release_photo(run_id)


@app.delete("/api/runs/{run_id}/photos/{slot}", dependencies=_RUN)
def api_delete_photo(run_id: str, slot: str):
    if not _claim_photo(run_id):
        return JSONResponse(status_code=409, content=_PHOTO_CLOSED)
    try:
        rd, err = _photo_guard(run_id, slot)
        if err:
            return err
        (rd / "05_photos" / f"{slot}.jpg").unlink(missing_ok=True)
        return {"deleted": True}
    finally:
        _release_photo(run_id)


@app.post("/api/runs/{run_id}/plan", status_code=202, dependencies=_ADMIN_WORK)
def api_run_plan(run_id: str):
    """Dev (used by /inspector): re-run only the plan node on a confirmed run; deletes its old results."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if load_record(run_id) is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_confirmed", "message": "Confirm is not done for this run."}
        })
    if not plan_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Plan is already running for this run."}
        })
    _clear_node(rd, "plan")  # old rows (and pre-step-2 06_plan/ folder)
    threading.Thread(target=_single_step, args=(run_id, "plan", run_plan), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/search", status_code=202, dependencies=_ADMIN_WORK)
def api_run_search(run_id: str):
    """Dev (used by /inspector): re-run only the search node on a run with plan queries; deletes its old results."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if load_result(run_id, "06_plan/queries.json") is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_queries", "message": "Plan has no queries for this run."}
        })
    if not search_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Search is already running for this run."}
        })
    _clear_node(rd, "search")  # this run's results.json (search_results keeps every result, by date)
    threading.Thread(target=_single_step, args=(run_id, "search", run_search), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/extract", status_code=202, dependencies=_ADMIN_WORK)
def api_run_extract(run_id: str):
    """Dev (used by /inspector): re-run only the extract node on a run with search results; deletes its old results."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if load_result(run_id, "07_search/results.json") is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_results", "message": "Search has no results for this run."}
        })
    if not extract_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Extract is already running for this run."}
        })
    _clear_node(rd, "extract")  # this run's extract rows (price_figures keeps every figure, by date)
    threading.Thread(target=_single_step, args=(run_id, "extract", run_extract), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/pricing", status_code=202, dependencies=_ADMIN_WORK)
def api_run_pricing(run_id: str):
    """Dev (used by /inspector): re-run only the pricing node on a run with extract figures; deletes its old price."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if load_result(run_id, "08_extract/figures.json") is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_figures", "message": "Extract has no figures for this run."}
        })
    if not pricing_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Pricing is already running for this run."}
        })
    _clear_node(rd, "pricing")  # price.json row + prices row; report.json stays until the report is re-run
    threading.Thread(target=_single_step, args=(run_id, "pricing", run_pricing), daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/report", status_code=202, dependencies=_ADMIN_WORK)
def api_run_report(run_id: str):
    """Dev (used by /inspector): rebuild only the report from the saved node results (no AI call)."""
    rd = _local_run(run_id, with_video=True)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if load_record(run_id) is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_confirmed", "message": "Confirm is not done for this run."}
        })
    if not report_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Report is already running for this run."}
        })
    threading.Thread(target=_single_step, args=(run_id, "report", run_report), daemon=True).start()
    return {"started": True}


@app.get("/api/cities", dependencies=_APPROVED)
def api_cities(state: str = ""):
    """City type-ahead list from the RTO table, optionally one state. The browser filters as you type."""
    rows = rto_rows()
    seen, out = set(), []
    for r in rows:
        if r["city"].lower().startswith("statewide") or (state and r["state"] != state):
            continue
        if (r["city"], r["state"]) not in seen:
            seen.add((r["city"], r["state"]))
            out.append({"city": r["city"], "state": r["state"]})
    return sorted(out, key=lambda c: c["city"])


@app.get("/api/runs/{run_id}/files/{path:path}", dependencies=_RUN)
def api_run_file(run_id: str, path: str):
    rd = _local_run(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    try:
        target = (rd / path).resolve()
        base = rd.resolve()
        target.relative_to(base)  # raises ValueError if outside base
    except ValueError:
        raise HTTPException(400, detail="Path is outside the run folder.")
    except Exception:
        raise HTTPException(400, detail="Invalid path.")

    if target.is_symlink():
        raise HTTPException(400, detail="Symlinks are not served.")

    if path in RESULT_FILES:  # saved in the database from stage 2.x, same JSON as the old file
        data = load_result(run_id, path)
        if data is None:
            raise HTTPException(404, detail=f"File not found: {path}")
        return PlainTextResponse(data) if path.endswith(".txt") else JSONResponse(data)

    if not target.exists():
        raise HTTPException(404, detail=f"File not found: {path}")

    return FileResponse(target)


@app.get("/inspector")
def inspector(request: Request):
    user = signed_in_user(request)
    if user is None or user.role != "admin":
        return RedirectResponse("/admin", status_code=303, headers=NO_STORE)
    return FileResponse(_INSPECTOR, headers=NO_STORE)  # never from the browser cache: a signed-out visit must redirect


@app.get("/openapi.json", dependencies=_ADMIN)
def openapi_json():
    return app.openapi()


@app.get("/docs", dependencies=_ADMIN)
def docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="CarLens API")
