from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .config import PROJECT_ROOT, get_config
from .confirm import load_rto
from .events import sse_stream
from .graph import is_paused, resume_from, resume_graph, run_graph
from .nodes.locate import run_locate
from .nodes.locate import try_claim as locate_try_claim
from .nodes.confirm import PAYLOAD_FILE, RECORD_FILE, finish_confirm, load_verify_answer, start_confirm
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
from .nodes.upload import process_upload
from .results import FILES as RESULT_FILES, delete_results, load_result
from .runs import append_event, events_path, failed_at, run_dir

# run_ids that have started or are starting the graph
_started: set[str] = set()
_start_lock = threading.Lock()

app = FastAPI(title="CarLens backend")


@app.on_event("startup")
def _startup():
    _warmup_tracing()


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


@app.get("/api/config")
def api_config():
    cfg = get_config()
    return {
        "upload": {
            "allowed_types": cfg.upload.allowed_types,
            "max_size_mb": cfg.upload.max_size_mb,
            "max_duration_sec": cfg.upload.max_duration_sec,
        },
        "nodes": _NODES,
    }


@app.post("/api/runs")
async def api_create_run(video: UploadFile = File(...)):
    return await process_upload(video)


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str):
    rd = run_dir(run_id)
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
    ep = events_path(run_id)
    if not ep.exists():
        return False
    with open(ep, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
                if ev.get("node") == "locate":
                    return True
            except json.JSONDecodeError:
                pass
    return False


@app.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str):
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    with _start_lock:
        if run_id not in _started and not _has_locate_event(run_id):
            _started.add(run_id)
            t = threading.Thread(target=run_graph, args=(run_id,), daemon=True)
            t.start()

    return StreamingResponse(
        sse_stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# What a node clears before it runs again (resume). Locate keeps video_small.mp4, photos keep the uploaded jpgs.
_NODE_FILES = {"locate": ["01_locate/request.json", "01_locate/response.json"],
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


@app.post("/api/runs/{run_id}/locate", status_code=202)
def api_run_locate(run_id: str):
    """Dev (used by /inspector): re-run only locate; reuses 01_locate/video_small.mp4 when the shrink already finished."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not locate_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Locate is already running for this run."}
        })
    _clear_node(rd, "locate")
    threading.Thread(target=run_locate, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/resume", status_code=202)
def api_resume(run_id: str):
    """Start the pipeline again at the node the run stopped at, then carry on to the end."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    node = failed_at(run_id)
    if node is None:
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_failed", "message": "Nothing to resume: the last run did not stop on a failure."}
        })
    with _resume_lock:
        if run_id in _resuming or is_paused(run_id):
            return JSONResponse(status_code=409, content={
                "error": {"code": "already_running", "message": "This run is already running or waiting for confirm."}
            })
        _resuming.add(run_id)
    _clear_node(rd, node)

    def _go():
        try:
            resume_from(run_id, node)
        finally:
            _resuming.discard(run_id)
    threading.Thread(target=_go, daemon=True).start()
    return {"resuming_from": node}


@app.post("/api/runs/{run_id}/frames", status_code=202)
def api_run_frames(run_id: str):
    rd = run_dir(run_id)
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

    threading.Thread(target=run_frames, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/verify", status_code=202)
def api_run_verify(run_id: str):
    rd = run_dir(run_id)
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

    threading.Thread(target=run_verify, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
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


@app.post("/api/runs/{run_id}/confirm/start")
def api_confirm_start(run_id: str):
    """Dev (used by /inspector): show the confirm step on a run whose graph already ended after verify."""
    rd = run_dir(run_id)
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
    (rd / PAYLOAD_FILE).unlink(missing_ok=True)
    (rd / RECORD_FILE).unlink(missing_ok=True)
    if (rd / "05_photos").exists():  # a fresh confirm starts without old photos
        shutil.rmtree(rd / "05_photos")
    start_confirm(run_id)
    return {"started": True}


@app.post("/api/runs/{run_id}/confirm")
def api_confirm(run_id: str, answer: ConfirmAnswer):
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    payload_path = rd / PAYLOAD_FILE
    with _confirm_lock:
        if not payload_path.exists():
            return JSONResponse(status_code=409, content={
                "error": {"code": "not_waiting", "message": "This run is not waiting for confirm."}
            })
        if (rd / RECORD_FILE).exists() or run_id in _confirming:
            return JSONResponse(status_code=409, content={
                "error": {"code": "already_confirmed", "message": "This run is already confirmed."}
            })
        _confirming.add(run_id)
    data = answer.model_dump()
    try:
        if is_paused(run_id):
            threading.Thread(target=resume_graph, args=(run_id, data), daemon=True).start()
        else:  # dev path: run started with "Start confirm", no graph waiting
            finish_confirm(run_id, json.loads(payload_path.read_text(encoding="utf-8")), data)
            # rest of the pipeline through the graph, so it stops at the first failed node like a normal run
            threading.Thread(target=resume_from, args=(run_id, "photos"), daemon=True).start()
    finally:
        _confirming.discard(run_id)  # 04_confirm.json now guards repeats
    return {"confirmed": True}


def _photo_guard(run_id: str, slot: str):
    """Photos can change only while confirm waits; the odometer slot only when the video read no km."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if slot not in SLOTS:
        raise HTTPException(404, detail=f"Unknown photo slot '{slot}'.")
    if not (rd / PAYLOAD_FILE).exists() or (rd / RECORD_FILE).exists():
        return rd, JSONResponse(status_code=409, content={
            "error": {"code": "not_waiting", "message": "Photos can only be changed while confirm is waiting."}
        })
    if slot == "odometer" and json.loads((rd / PAYLOAD_FILE).read_text(encoding="utf-8")).get("odometer_found"):
        return rd, JSONResponse(status_code=409, content={
            "error": {"code": "odometer_read", "message": "The video already read the odometer."}
        })
    return rd, None


@app.post("/api/runs/{run_id}/photos/{slot}")
async def api_upload_photo(run_id: str, slot: str, photo: UploadFile = File(...)):
    """Stage 6: one extra photo per slot (front_left, front_right, rear_left, rear_right, odometer); replaces the old one."""
    rd, err = _photo_guard(run_id, slot)
    if err:
        return err
    data = await photo.read(get_config().photos.max_size_mb * 1024 * 1024 + 1)
    problem = save_photo(rd / "05_photos", slot, photo.filename or "", data)
    if problem:
        return JSONResponse(status_code=422, content={"error": {"code": "bad_photo", "message": problem}})
    return {"saved": f"05_photos/{slot}.jpg"}


@app.delete("/api/runs/{run_id}/photos/{slot}")
def api_delete_photo(run_id: str, slot: str):
    rd, err = _photo_guard(run_id, slot)
    if err:
        return err
    (rd / "05_photos" / f"{slot}.jpg").unlink(missing_ok=True)
    return {"deleted": True}


@app.post("/api/runs/{run_id}/plan", status_code=202)
def api_run_plan(run_id: str):
    """Dev (used by /inspector): re-run only the plan node on a confirmed run; deletes old 06_plan/."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not (rd / RECORD_FILE).exists():
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_confirmed", "message": "Confirm is not done for this run."}
        })
    if not plan_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Plan is already running for this run."}
        })
    if (rd / "06_plan").exists():
        shutil.rmtree(rd / "06_plan")
    threading.Thread(target=run_plan, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/search", status_code=202)
def api_run_search(run_id: str):
    """Dev (used by /inspector): re-run only the search node on a run with plan queries; deletes old 07_search/."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not (rd / "06_plan" / "queries.json").exists():
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_queries", "message": "Plan has no queries for this run."}
        })
    if not search_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Search is already running for this run."}
        })
    if (rd / "07_search").exists():
        shutil.rmtree(rd / "07_search")
    threading.Thread(target=run_search, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/extract", status_code=202)
def api_run_extract(run_id: str):
    """Dev (used by /inspector): re-run only the extract node on a run with search results; deletes old 08_extract/."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not (rd / "07_search" / "results.json").exists():
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_results", "message": "Search has no results for this run."}
        })
    if not extract_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Extract is already running for this run."}
        })
    if (rd / "08_extract").exists():
        shutil.rmtree(rd / "08_extract")
    threading.Thread(target=run_extract, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/pricing", status_code=202)
def api_run_pricing(run_id: str):
    """Dev (used by /inspector): re-run only the pricing node on a run with extract figures; deletes old 09_report/."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not (rd / "08_extract" / "figures.json").exists():
        return JSONResponse(status_code=409, content={
            "error": {"code": "no_figures", "message": "Extract has no figures for this run."}
        })
    if not pricing_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Pricing is already running for this run."}
        })
    (rd / "09_report" / "price.json").unlink(missing_ok=True)  # report.json stays until the report is re-run
    threading.Thread(target=run_pricing, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.post("/api/runs/{run_id}/report", status_code=202)
def api_run_report(run_id: str):
    """Dev (used by /inspector): rebuild only the report from the files already in the run folder (no AI call)."""
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")
    if not (rd / RECORD_FILE).exists():
        return JSONResponse(status_code=409, content={
            "error": {"code": "not_confirmed", "message": "Confirm is not done for this run."}
        })
    if not report_try_claim(run_id):
        return JSONResponse(status_code=409, content={
            "error": {"code": "already_running", "message": "Report is already running for this run."}
        })
    threading.Thread(target=run_report, args=(run_id,), kwargs={"claimed": True}, daemon=True).start()
    return {"started": True}


@app.get("/api/cities")
def api_cities(state: str = ""):
    """City type-ahead list from the RTO table, optionally one state. The browser filters as you type."""
    rows = load_rto(PROJECT_ROOT / get_config().paths.rto_csv)
    seen, out = set(), []
    for r in rows:
        if r["city"].lower().startswith("statewide") or (state and r["state"] != state):
            continue
        if (r["city"], r["state"]) not in seen:
            seen.add((r["city"], r["state"]))
            out.append({"city": r["city"], "state": r["state"]})
    return sorted(out, key=lambda c: c["city"])


@app.get("/api/runs/{run_id}/files/{path:path}")
def api_run_file(run_id: str, path: str):
    rd = run_dir(run_id)
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
        return JSONResponse(data)

    if not target.exists():
        raise HTTPException(404, detail=f"File not found: {path}")

    return FileResponse(target)


@app.get("/inspector")
def inspector():
    return FileResponse(_INSPECTOR)
